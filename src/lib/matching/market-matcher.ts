import { eq, and, inArray, isNotNull } from 'drizzle-orm';
import { getDb } from '@/lib/db';
import { markets, matchGroups } from '@/lib/db/schema';
import {
  jaccardSimilarity,
  normalizedSimilarity,
} from '@/lib/utils/math';

const STOPWORDS = new Set([
  'a', 'an', 'the', 'will', 'is', 'are', 'be', 'to', 'of', 'in',
  'on', 'at', 'by', 'for', 'with', 'and', 'or', 'but',
]);

/**
 * Normalize a market title for comparison.
 * Lowercases, strips punctuation, removes stopwords, collapses whitespace.
 */
export function normalizeTitle(title: string): string {
  if (!title) return '';
  const lowered = title.toLowerCase();
  // Replace anything that isn't a letter, digit, or whitespace with a space.
  const stripped = lowered.replace(/[^\p{L}\p{N}\s]/gu, ' ');
  const tokens = stripped
    .split(/\s+/)
    .map((t) => t.trim())
    .filter((t) => t.length > 0 && !STOPWORDS.has(t));
  return tokens.join(' ').trim();
}

/**
 * Extract a set of meaningful keywords (length >= 3, normalized).
 */
export function extractKeywords(title: string): Set<string> {
  const normalized = normalizeTitle(title);
  const tokens = normalized.split(/\s+/).filter((t) => t.length >= 3);
  return new Set(tokens);
}

/**
 * Compute similarity score between two titles in range [0, 1].
 * Combines Jaccard similarity on keyword sets (0.5) and normalized
 * Levenshtein on normalized titles (0.5). If categories match, boost by 0.1.
 */
export function computeSimilarity(
  titleA: string,
  titleB: string,
  categoryA?: string,
  categoryB?: string
): number {
  const normalizedA = normalizeTitle(titleA);
  const normalizedB = normalizeTitle(titleB);

  if (!normalizedA && !normalizedB) return 0;

  const keywordsA = extractKeywords(titleA);
  const keywordsB = extractKeywords(titleB);

  const jaccard = jaccardSimilarity(keywordsA, keywordsB);
  const editSim = normalizedSimilarity(normalizedA, normalizedB);

  let score = 0.5 * jaccard + 0.5 * editSim;

  if (
    categoryA &&
    categoryB &&
    categoryA.toLowerCase() === categoryB.toLowerCase()
  ) {
    score += 0.1;
  }

  if (score > 1) score = 1;
  if (score < 0) score = 0;
  return score;
}

// --- Union-Find -----------------------------------------------------------

class UnionFind {
  private parent: Map<string, string> = new Map();
  private rank: Map<string, number> = new Map();

  add(id: string): void {
    if (!this.parent.has(id)) {
      this.parent.set(id, id);
      this.rank.set(id, 0);
    }
  }

  find(id: string): string {
    let current = id;
    while (this.parent.get(current) !== current) {
      const parent = this.parent.get(current)!;
      const grandparent = this.parent.get(parent)!;
      this.parent.set(current, grandparent);
      current = grandparent;
    }
    return current;
  }

  union(a: string, b: string): void {
    const rootA = this.find(a);
    const rootB = this.find(b);
    if (rootA === rootB) return;
    const rankA = this.rank.get(rootA) ?? 0;
    const rankB = this.rank.get(rootB) ?? 0;
    if (rankA < rankB) {
      this.parent.set(rootA, rootB);
    } else if (rankA > rankB) {
      this.parent.set(rootB, rootA);
    } else {
      this.parent.set(rootB, rootA);
      this.rank.set(rootA, rankA + 1);
    }
  }

  groups(): Map<string, string[]> {
    const groups = new Map<string, string[]>();
    for (const id of this.parent.keys()) {
      const root = this.find(id);
      if (!groups.has(root)) groups.set(root, []);
      groups.get(root)!.push(id);
    }
    return groups;
  }
}

/**
 * Find matches across all active markets, populate matchGroups table,
 * and update markets.matchGroupId. Uses union-find for transitive merging.
 */
export async function runMarketMatching(
  threshold = 0.7
): Promise<{ groupsCreated: number; marketsMatched: number }> {
  const db = getDb();

  try {
    const activeMarkets = await db
      .select({
        id: markets.id,
        platform: markets.platform,
        title: markets.title,
        category: markets.category,
      })
      .from(markets)
      .where(eq(markets.status, 'active'));

    if (activeMarkets.length < 2) {
      return { groupsCreated: 0, marketsMatched: 0 };
    }

    const uf = new UnionFind();
    for (const m of activeMarkets) {
      uf.add(m.id);
    }

    // Precompute keywords/normalized titles once for speed.
    const prepared = activeMarkets.map((m) => ({
      id: m.id,
      platform: m.platform,
      title: m.title,
      category: m.category,
      normalized: normalizeTitle(m.title),
      keywords: extractKeywords(m.title),
    }));

    for (let i = 0; i < prepared.length; i++) {
      const a = prepared[i];
      for (let j = i + 1; j < prepared.length; j++) {
        const b = prepared[j];

        // Skip if same platform AND same platform market id (shouldn't happen
        // but guard anyway). We still want within-platform matches for some
        // cases (e.g., duplicates), so do not skip by platform alone.
        const sameCategory =
          !!a.category &&
          !!b.category &&
          a.category.toLowerCase() === b.category.toLowerCase();
        const effectiveThreshold = sameCategory ? 0.65 : threshold;

        const jaccard = jaccardSimilarity(a.keywords, b.keywords);
        const editSim = normalizedSimilarity(a.normalized, b.normalized);
        let score = 0.5 * jaccard + 0.5 * editSim;
        if (sameCategory) score += 0.1;
        if (score > 1) score = 1;

        if (score >= effectiveThreshold) {
          uf.union(a.id, b.id);
        }
      }
    }

    const groups = uf.groups();
    let groupsCreated = 0;
    let marketsMatched = 0;
    const now = Date.now();

    for (const [, memberIds] of groups) {
      if (memberIds.length < 2) continue;

      // Determine a canonical title (shortest meaningful one) and the most
      // common category across members.
      const members = prepared.filter((p) => memberIds.includes(p.id));
      const canonical = members
        .slice()
        .sort((x, y) => x.title.length - y.title.length)[0].title;

      const categoryCounts = new Map<string, number>();
      for (const m of members) {
        if (m.category) {
          categoryCounts.set(
            m.category,
            (categoryCounts.get(m.category) ?? 0) + 1
          );
        }
      }
      let chosenCategory: string | null = null;
      let maxCount = 0;
      for (const [cat, count] of categoryCounts) {
        if (count > maxCount) {
          maxCount = count;
          chosenCategory = cat;
        }
      }

      const groupId = crypto.randomUUID();

      try {
        await db
          .insert(matchGroups)
          .values({
            id: groupId,
            canonicalTitle: canonical,
            category: chosenCategory,
            marketCount: memberIds.length,
            createdAt: now,
          });

        await db
          .update(markets)
          .set({ matchGroupId: groupId, updatedAt: now })
          .where(inArray(markets.id, memberIds));

        groupsCreated++;
        marketsMatched += memberIds.length;
      } catch (err) {
        console.error(
          `[market-matcher] Failed to persist group for ${memberIds.length} markets:`,
          err
        );
      }
    }

    return { groupsCreated, marketsMatched };
  } catch (err) {
    console.error('[market-matcher] runMarketMatching failed:', err);
    throw err;
  }
}

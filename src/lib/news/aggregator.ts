import { getDb } from '@/lib/db';
import { markets, newsItems } from '@/lib/db/schema';
import { desc, eq } from 'drizzle-orm';

export interface NormalizedNewsItem {
  title: string;
  summary?: string;
  url: string;
  source: string;
  imageUrl?: string;
  publishedAt: Date;
}

const STOPWORDS = new Set([
  'a', 'an', 'the', 'will', 'is', 'are', 'be', 'to', 'of', 'in', 'on',
  'at', 'by', 'for', 'with', 'and', 'or', 'but', 'this', 'that', 'than',
  'what', 'when', 'who', 'how', 'why', 'which',
]);

function extractKeywords(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .split(/\s+/)
    .filter((w) => w.length >= 3 && !STOPWORDS.has(w));
}

function extractBetween(str: string, start: string, end: string): string {
  const i = str.indexOf(start);
  if (i < 0) return '';
  const j = str.indexOf(end, i + start.length);
  if (j < 0) return '';
  return str.substring(i + start.length, j);
}

function stripCdata(s: string): string {
  return s.replace(/^<!\[CDATA\[/, '').replace(/\]\]>$/, '').trim();
}

function decodeHtmlEntities(s: string): string {
  return s
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'");
}

export async function fetchGoogleNews(query: string): Promise<NormalizedNewsItem[]> {
  try {
    const url = `https://news.google.com/rss/search?q=${encodeURIComponent(query)}&hl=en-US&gl=US&ceid=US:en`;
    const res = await fetch(url, {
      headers: { 'User-Agent': 'Mozilla/5.0 PredictionMarketTracker/1.0' },
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) return [];
    const xml = await res.text();
    const items: NormalizedNewsItem[] = [];
    const parts = xml.split('<item>').slice(1);
    for (const part of parts.slice(0, 15)) {
      const title = stripCdata(extractBetween(part, '<title>', '</title>'));
      const link = stripCdata(extractBetween(part, '<link>', '</link>'));
      const pubDate = extractBetween(part, '<pubDate>', '</pubDate>');
      const source = stripCdata(extractBetween(part, '<source', '</source>')).replace(/^[^>]*>/, '');
      const description = stripCdata(extractBetween(part, '<description>', '</description>'));
      if (title && link) {
        items.push({
          title: decodeHtmlEntities(title),
          url: link,
          source: source || 'Google News',
          summary: decodeHtmlEntities(description.replace(/<[^>]+>/g, '').trim()).slice(0, 300),
          publishedAt: pubDate ? new Date(pubDate) : new Date(),
        });
      }
    }
    return items;
  } catch (err) {
    console.error('[news] Google News fetch failed:', err);
    return [];
  }
}

export async function fetchRedditRSS(
  subreddit = 'predictit+polymarket+kalshi'
): Promise<NormalizedNewsItem[]> {
  try {
    const url = `https://www.reddit.com/r/${subreddit}/.rss`;
    const res = await fetch(url, {
      headers: { 'User-Agent': 'PredictionMarketTracker/1.0 (by /u/local)' },
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) return [];
    const xml = await res.text();
    const items: NormalizedNewsItem[] = [];
    const parts = xml.split('<entry>').slice(1);
    for (const part of parts.slice(0, 15)) {
      const title = stripCdata(extractBetween(part, '<title>', '</title>'));
      const linkMatch = part.match(/<link[^>]*href="([^"]+)"/);
      const link = linkMatch?.[1] ?? '';
      const updated = extractBetween(part, '<updated>', '</updated>');
      if (title && link) {
        items.push({
          title: decodeHtmlEntities(title),
          url: link,
          source: `Reddit: r/${subreddit}`,
          publishedAt: updated ? new Date(updated) : new Date(),
        });
      }
    }
    return items;
  } catch (err) {
    console.error('[news] Reddit RSS fetch failed:', err);
    return [];
  }
}

export function scoreRelevance(
  newsText: string,
  marketKeywordSets: Array<{ marketId: string; keywords: Set<string> }>
): { score: number; relatedIds: string[] } {
  const newsKeywords = new Set(extractKeywords(newsText));
  if (newsKeywords.size === 0) return { score: 0, relatedIds: [] };

  let maxScore = 0;
  const related: string[] = [];

  for (const { marketId, keywords } of marketKeywordSets) {
    if (keywords.size === 0) continue;
    let matches = 0;
    for (const kw of keywords) {
      if (newsKeywords.has(kw)) matches++;
    }
    const score = matches / keywords.size;
    if (score > 0.3) related.push(marketId);
    if (score > maxScore) maxScore = score;
  }

  return { score: maxScore, relatedIds: related };
}

export async function aggregateNews(): Promise<{ fetched: number; stored: number }> {
  const db = getDb();

  // Get top active markets
  const topMarkets = await db
    .select({ id: markets.id, title: markets.title })
    .from(markets)
    .where(eq(markets.status, 'active'))
    .orderBy(desc(markets.volume))
    .limit(20);

  const marketKeywordSets = topMarkets.map((m) => ({
    marketId: m.id,
    keywords: new Set(extractKeywords(m.title)),
  }));

  // Pick top search terms (up to 4 queries)
  const topTerms: string[] = [];
  const seenTerms = new Set<string>();
  for (const m of topMarkets.slice(0, 10)) {
    const words = extractKeywords(m.title).slice(0, 2);
    const term = words.join(' ');
    if (term && !seenTerms.has(term)) {
      seenTerms.add(term);
      topTerms.push(term);
      if (topTerms.length >= 4) break;
    }
  }

  // Fetch news
  const allNews: NormalizedNewsItem[] = [];
  const newsQueries = [
    ...topTerms.map((t) => fetchGoogleNews(t)),
    fetchRedditRSS(),
  ];
  const results = await Promise.allSettled(newsQueries);
  for (const r of results) {
    if (r.status === 'fulfilled') allNews.push(...r.value);
  }

  // Deduplicate by URL
  const byUrl = new Map<string, NormalizedNewsItem>();
  for (const item of allNews) {
    if (!byUrl.has(item.url)) byUrl.set(item.url, item);
  }
  const unique = Array.from(byUrl.values());

  // Score relevance and store
  const now = new Date();
  let stored = 0;
  for (const item of unique) {
    const searchText = `${item.title} ${item.summary ?? ''}`;
    const { score, relatedIds } = scoreRelevance(searchText, marketKeywordSets);

    // Check if URL already exists
    const existing = await db
      .select({ id: newsItems.id })
      .from(newsItems)
      .where(eq(newsItems.url, item.url))
      .limit(1);

    if (existing.length > 0) continue;

    try {
      await db.insert(newsItems).values({
        title: item.title,
        summary: item.summary ?? null,
        url: item.url,
        source: item.source,
        imageUrl: item.imageUrl ?? null,
        publishedAt: Math.floor(item.publishedAt.getTime() / 1000),
        fetchedAt: Math.floor(now.getTime() / 1000),
        relatedMarketIds: relatedIds as unknown as string,
        relevanceScore: score,
        keywords: extractKeywords(searchText).slice(0, 15) as unknown as string,
      });
      stored++;
    } catch (err) {
      console.error('[news] Failed to insert item:', err);
    }
  }

  return { fetched: unique.length, stored };
}

'use client';

import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { PLATFORMS } from '@/lib/utils/constants';
import { formatPercent } from '@/lib/utils/format';
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  Line,
  BarChart,
  Bar,
  LineChart,
  Legend,
} from 'recharts';

interface CalibrationPoint {
  bucket: string;
  predictedRange: [number, number];
  actualResolutionRate: number;
  sampleSize: number;
  platform: string;
}

interface ProbComparison {
  matchGroupId: string;
  canonicalTitle: string;
  prices: Record<string, number>;
  disagreement: number;
}

interface Distribution {
  bucket: string;
  count: number;
}

function useProb<T>(view: string) {
  return useQuery<{ data: T }>({
    queryKey: ['probability', view],
    queryFn: async () => {
      const res = await fetch(`/api/probability?view=${view}`);
      if (!res.ok) throw new Error('Failed');
      return res.json();
    },
    refetchInterval: 300_000,
  });
}

function CalibrationView() {
  const { data, isLoading } = useProb<CalibrationPoint[]>('calibration');
  const points = data?.data ?? [];

  // Group by platform
  const byPlatform: Record<string, Array<{ predicted: number; actual: number; size: number }>> = {};
  points.forEach((p) => {
    if (!byPlatform[p.platform]) byPlatform[p.platform] = [];
    const midPredicted = (p.predictedRange[0] + p.predictedRange[1]) / 2;
    byPlatform[p.platform].push({
      predicted: midPredicted * 100,
      actual: p.actualResolutionRate * 100,
      size: p.sampleSize,
    });
  });

  if (isLoading) {
    return <div className="py-8 text-center text-sm text-zinc-500">Loading calibration...</div>;
  }

  if (points.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-zinc-500">
        No resolved markets yet. Calibration requires historical data.
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={400}>
      <ScatterChart margin={{ top: 10, right: 10, left: 0, bottom: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
        <XAxis
          type="number"
          dataKey="predicted"
          name="Predicted"
          domain={[0, 100]}
          unit="%"
          stroke="#52525b"
          tick={{ fill: '#a1a1aa', fontSize: 11 }}
        />
        <YAxis
          type="number"
          dataKey="actual"
          name="Actual"
          domain={[0, 100]}
          unit="%"
          stroke="#52525b"
          tick={{ fill: '#a1a1aa', fontSize: 11 }}
        />
        <RechartsTooltip
          contentStyle={{ backgroundColor: '#18181b', border: '1px solid #3f3f46' }}
          cursor={{ strokeDasharray: '3 3' }}
        />
        <Legend />
        {Object.entries(byPlatform).map(([platform, data]) => (
          <Scatter
            key={platform}
            name={PLATFORMS[platform as keyof typeof PLATFORMS]?.name ?? platform}
            data={data}
            fill={PLATFORMS[platform as keyof typeof PLATFORMS]?.color ?? '#6366f1'}
          />
        ))}
      </ScatterChart>
    </ResponsiveContainer>
  );
}

function ComparisonView() {
  const { data, isLoading } = useProb<ProbComparison[]>('comparison');
  const comparisons = data?.data ?? [];

  if (isLoading) {
    return <div className="py-8 text-center text-sm text-zinc-500">Loading comparisons...</div>;
  }

  if (comparisons.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-zinc-500">
        No matched markets found. Cross-platform matching runs every 5 minutes.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-zinc-900/60 text-xs uppercase tracking-wider text-zinc-500">
          <tr>
            <th className="px-4 py-2.5 text-left font-medium">Market</th>
            {Object.keys(PLATFORMS).map((p) => (
              <th key={p} className="px-3 py-2.5 text-right font-medium">
                {PLATFORMS[p as keyof typeof PLATFORMS].shortName}
              </th>
            ))}
            <th className="px-3 py-2.5 text-right font-medium">Disagreement</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/60">
          {comparisons.map((c) => (
            <tr key={c.matchGroupId} className="hover:bg-zinc-900/60">
              <td className="max-w-md truncate px-4 py-2.5 text-zinc-100">
                {c.canonicalTitle}
              </td>
              {Object.keys(PLATFORMS).map((p) => (
                <td key={p} className="px-3 py-2.5 text-right font-mono text-zinc-200">
                  {c.prices[p] !== undefined ? `${(c.prices[p] * 100).toFixed(1)}¢` : '—'}
                </td>
              ))}
              <td className="px-3 py-2.5 text-right font-mono font-semibold text-amber-400">
                {formatPercent(c.disagreement)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DistributionView() {
  const { data, isLoading } = useProb<Distribution[]>('distribution');
  const distribution = data?.data ?? [];

  if (isLoading) {
    return <div className="py-8 text-center text-sm text-zinc-500">Loading distribution...</div>;
  }

  return (
    <ResponsiveContainer width="100%" height={400}>
      <BarChart data={distribution} margin={{ top: 10, right: 10, left: 0, bottom: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />
        <XAxis
          dataKey="bucket"
          stroke="#52525b"
          tick={{ fill: '#a1a1aa', fontSize: 10 }}
          interval={0}
          angle={-45}
          textAnchor="end"
          height={60}
        />
        <YAxis stroke="#52525b" tick={{ fill: '#a1a1aa', fontSize: 11 }} />
        <RechartsTooltip
          contentStyle={{ backgroundColor: '#18181b', border: '1px solid #3f3f46' }}
        />
        <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export default function ProbabilityPage() {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-50">Probability Analysis</h1>
        <p className="mt-1 text-sm text-zinc-400">
          Calibration, cross-platform comparison, and probability distributions
        </p>
      </div>

      <Tabs defaultValue="calibration">
        <TabsList>
          <TabsTrigger value="calibration">Calibration</TabsTrigger>
          <TabsTrigger value="comparison">Cross-Platform</TabsTrigger>
          <TabsTrigger value="distribution">Distribution</TabsTrigger>
        </TabsList>
        <TabsContent value="calibration">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Calibration Curve</CardTitle>
              <p className="mt-1 text-xs text-zinc-500">
                Predicted probability (x) vs actual resolution rate (y). Points close to diagonal = well calibrated.
              </p>
            </CardHeader>
            <CardContent>
              <CalibrationView />
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="comparison">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Cross-Platform Price Comparison</CardTitle>
              <p className="mt-1 text-xs text-zinc-500">
                Markets that appear on multiple platforms, sorted by disagreement.
              </p>
            </CardHeader>
            <CardContent className="p-0">
              <ComparisonView />
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="distribution">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Probability Distribution</CardTitle>
              <p className="mt-1 text-xs text-zinc-500">
                How current market YES prices are distributed across the 0-100% range.
              </p>
            </CardHeader>
            <CardContent>
              <DistributionView />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

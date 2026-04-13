import { NextRequest, NextResponse } from 'next/server';
import {
  computeCalibration,
  computeCrossPlatformComparison,
  computeProbabilityDistribution,
} from '@/lib/analysis/probability';

type View = 'calibration' | 'comparison' | 'distribution';

const VALID_VIEWS: ReadonlySet<View> = new Set<View>([
  'calibration',
  'comparison',
  'distribution',
]);

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl;
    const viewParam = (searchParams.get('view') ?? 'calibration') as View;

    if (!VALID_VIEWS.has(viewParam)) {
      return NextResponse.json(
        {
          error: `Invalid view: ${viewParam}. Must be one of: calibration, comparison, distribution`,
        },
        { status: 400 },
      );
    }

    switch (viewParam) {
      case 'calibration': {
        const points = await computeCalibration();
        return NextResponse.json({ view: 'calibration', data: points });
      }
      case 'comparison': {
        const data = await computeCrossPlatformComparison();
        return NextResponse.json({ view: 'comparison', data });
      }
      case 'distribution': {
        const data = await computeProbabilityDistribution();
        return NextResponse.json({ view: 'distribution', data });
      }
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown error';
    console.error('[GET /api/probability] Failed:', error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

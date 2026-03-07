import { useMemo } from 'react';
import { useTheme } from '@mui/material/styles';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Typography from '@mui/material/Typography';
import Stack from '@mui/material/Stack';
import { LineChart } from '@mui/x-charts/LineChart';

function AreaGradient({ color, id }: { color: string; id: string }) {
  return (
    <defs>
      <linearGradient id={id} x1="50%" y1="0%" x2="50%" y2="100%">
        <stop offset="0%" stopColor={color} stopOpacity={0.5} />
        <stop offset="100%" stopColor={color} stopOpacity={0} />
      </linearGradient>
    </defs>
  );
}

type SeriesDatum = {
  id: string;
  label: string;
  data: number[];
};

type SessionsChartProps = {
  title?: string;
  totalValue?: string;
  deltaLabel?: string;
  subtitle?: string;
  labels?: string[];
  series?: SeriesDatum[];
};

export default function SessionsChart({
  title = 'Survey hours',
  totalValue = '--',
  deltaLabel,
  subtitle = 'Survey hours per day for the last 30 days',
  labels,
  series,
}: SessionsChartProps) {
  const theme = useTheme();
  const finalSeries = series ?? [];
  const hasSeries = finalSeries.length > 0 && finalSeries.some((item) => item.data.length > 0);
  const maxLen = hasSeries
    ? Math.max(...finalSeries.map((item) => item.data.length))
    : 0;
  const fallbackLabels = maxLen > 0 ? Array.from({ length: maxLen }, (_, i) => `${i + 1}`) : [];
  const xLabels =
    labels && labels.length === maxLen ? labels : fallbackLabels;

  const colorPalette = useMemo(
    () => [
      theme.palette.primary.light,
      theme.palette.primary.main,
      theme.palette.primary.dark,
    ],
    [theme.palette.primary.dark, theme.palette.primary.light, theme.palette.primary.main],
  );

  return (
    <Card variant="outlined" sx={{ width: '100%' }}>
      <CardContent>
        <Typography component="h2" variant="subtitle2" gutterBottom>
          {title}
        </Typography>
        <Stack sx={{ justifyContent: 'space-between' }}>
          <Stack
            direction="row"
            sx={{
              alignContent: { xs: 'center', sm: 'flex-start' },
              alignItems: 'center',
              gap: 1,
            }}
          >
            <Typography variant="h4" component="p">
              {totalValue}
            </Typography>
            {deltaLabel && <Chip size="small" color="success" label={deltaLabel} />}
          </Stack>
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            {subtitle}
          </Typography>
        </Stack>
        {hasSeries ? (
          <LineChart
            colors={colorPalette}
            xAxis={[
              {
                scaleType: 'point',
                data: xLabels,
                tickInterval: (value, index) =>
                  (index + 1) % 5 === 0 && value !== undefined,
                height: 24,
              },
            ]}
            yAxis={[{ width: 50 }]}
            series={finalSeries.map((serie) => ({
              id: serie.id,
              label: serie.label,
              showMark: false,
              curve: 'linear',
              stack: 'total',
              area: true,
              stackOrder: 'ascending',
              data: serie.data,
            }))}
            height={250}
            margin={{ left: 0, right: 20, top: 20, bottom: 0 }}
            grid={{ horizontal: true }}
            sx={{
              ...finalSeries.reduce<Record<string, any>>((acc, serie) => {
                acc[`& .MuiAreaElement-series-${serie.id}`] = {
                  fill: `url('#area-${serie.id}')`,
                };
                return acc;
              }, {}),
            }}
            hideLegend
          >
            {finalSeries.map((serie, idx) => (
              <AreaGradient
                key={serie.id}
                color={colorPalette[idx % colorPalette.length]}
                id={`area-${serie.id}`}
              />
            ))}
          </LineChart>
        ) : (
          <Typography variant="body2" sx={{ mt: 2, color: 'text.secondary' }}>
            No data yet
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}

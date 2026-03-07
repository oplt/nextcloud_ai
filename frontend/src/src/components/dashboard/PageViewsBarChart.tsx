import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import Typography from '@mui/material/Typography';
import Stack from '@mui/material/Stack';
import { BarChart } from '@mui/x-charts/BarChart';
import { useTheme } from '@mui/material/styles';

type WorkloadSeries = { id: string; label: string; data: number[] };

type PageViewsBarChartProps = {
  title?: string;
  totalValue?: string;
  deltaLabel?: string;
  subtitle?: string;
  labels?: string[];
  series?: WorkloadSeries[];
};

export default function PageViewsBarChart({
  title = 'Flight workload',
  totalValue = '--',
  deltaLabel,
  subtitle = 'Flight executions and imagery exports for the last 6 months',
  labels,
  series,
}: PageViewsBarChartProps) {
  const theme = useTheme();
  const colorPalette = [
    (theme.vars || theme).palette.primary.dark,
    (theme.vars || theme).palette.primary.main,
    (theme.vars || theme).palette.primary.light,
  ];
  const finalSeries = series ?? [];
  const hasSeries = finalSeries.length > 0 && finalSeries.some((item) => item.data.length > 0);
  const maxLen = hasSeries
    ? Math.max(...finalSeries.map((item) => item.data.length))
    : 0;
  const fallbackLabels = maxLen > 0 ? Array.from({ length: maxLen }, (_, i) => `${i + 1}`) : [];
  const xLabels =
    labels && labels.length === maxLen ? labels : fallbackLabels;
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
          <BarChart
            borderRadius={8}
            colors={colorPalette}
            xAxis={[
              {
                scaleType: 'band',
                categoryGapRatio: 0.5,
                data: xLabels,
                height: 24,
              },
            ]}
            yAxis={[{ width: 50 }]}
            series={finalSeries.map((serie) => ({
              id: serie.id,
              label: serie.label,
              data: serie.data,
              stack: 'A',
            }))}
            height={250}
            margin={{ left: 0, right: 0, top: 20, bottom: 0 }}
            grid={{ horizontal: true }}
            hideLegend
          />
        ) : (
          <Typography variant="body2" sx={{ mt: 2, color: 'text.secondary' }}>
            No data yet
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}

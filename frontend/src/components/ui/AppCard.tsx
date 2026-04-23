import Card from '@mui/material/Card';
import type { CardProps } from '@mui/material/Card';

export function AppCard(props: CardProps) {
  return (
    <Card
      elevation={0}
      {...props}
    />
  );
}

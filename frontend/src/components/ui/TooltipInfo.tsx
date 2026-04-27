import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import IconButton from '@mui/material/IconButton';
import Tooltip from '@mui/material/Tooltip';

type TooltipInfoProps = {
  title: string;
  ariaLabel?: string;
  placement?: 'top' | 'right' | 'bottom' | 'left';
};

export function TooltipInfo({
  title,
  ariaLabel = 'More info',
  placement = 'top',
}: TooltipInfoProps) {
  return (
    <Tooltip title={title} placement={placement} arrow>
      <IconButton
        size="small"
        aria-label={ariaLabel}
        className="tooltip-info"
      >
        <InfoOutlinedIcon fontSize="inherit" />
      </IconButton>
    </Tooltip>
  );
}

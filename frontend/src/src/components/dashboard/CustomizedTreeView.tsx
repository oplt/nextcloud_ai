import * as React from 'react';
import clsx from 'clsx';
import { animated, useSpring } from '@react-spring/web';
import type { TransitionProps } from "@mui/material/transitions";
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Collapse from '@mui/material/Collapse';
import Typography from '@mui/material/Typography';
import { RichTreeView } from '@mui/x-tree-view/RichTreeView';
import { useTreeItem } from "@mui/x-tree-view/useTreeItem";
import type { UseTreeItemParameters } from "@mui/x-tree-view/useTreeItem";
import {
  TreeItemContent,
  TreeItemIconContainer,
  TreeItemLabel,
  TreeItemRoot,
} from '@mui/x-tree-view/TreeItem';
import { TreeItemIcon } from '@mui/x-tree-view/TreeItemIcon';
import { TreeItemProvider } from '@mui/x-tree-view/TreeItemProvider';
import type { TreeViewBaseItem } from "@mui/x-tree-view/models";
import { useTheme } from '@mui/material/styles';

type Color = 'blue' | 'green';

type ExtendedTreeItemProps = {
  color?: Color;
  id: string;
  label: string;
};

type SummarySnapshot = {
  active_flights?: number | null;
  flights_24h?: number | null;
  telemetry_24h?: number | null;
  flight_hours_7d?: number | null;
  avg_battery_24h?: number | null;
};

type SystemSnapshot = {
  telemetry_running?: boolean;
  mavlink_connected?: boolean;
  active_connections?: number | null;
};

type CoverageSegment = {
  label: string;
  value: number;
};

type CustomizedTreeViewProps = {
  summary?: SummarySnapshot;
  system?: SystemSnapshot;
  coverage?: CoverageSegment[];
};

const formatNumber = (value: number | null | undefined, suffix = '') => {
  if (value === null || value === undefined || Number.isNaN(value)) return 'No data';
  return `${value.toLocaleString()}${suffix}`;
};

const formatHours = (value: number | null | undefined) => {
  if (value === null || value === undefined || Number.isNaN(value)) return 'No data';
  return `${value.toFixed(1)}h`;
};

function DotIcon({ color }: { color: string }) {
  return (
    <Box sx={{ marginRight: 1, display: 'flex', alignItems: 'center' }}>
      <svg width={6} height={6}>
        <circle cx={3} cy={3} r={3} fill={color} />
      </svg>
    </Box>
  );
}

const AnimatedCollapse = animated(Collapse);

function TransitionComponent(props: TransitionProps) {
  const style = useSpring({
    to: {
      opacity: props.in ? 1 : 0,
      transform: `translate3d(0,${props.in ? 0 : 20}px,0)`,
    },
  });

  return <AnimatedCollapse style={style} {...props} />;
}

interface CustomLabelProps {
  children: React.ReactNode;
  color?: Color;
  expandable?: boolean;
}

function CustomLabel({ color, expandable, children, ...other }: CustomLabelProps) {
  const theme = useTheme();
  const colors = {
    blue: (theme.vars || theme).palette.primary.main,
    green: (theme.vars || theme).palette.success.main,
  };

  const iconColor = color ? colors[color] : null;
  return (
    <TreeItemLabel {...other} sx={{ display: 'flex', alignItems: 'center' }}>
      {iconColor && <DotIcon color={iconColor} />}
      <Typography
        className="labelText"
        variant="body2"
        sx={{ color: 'text.primary' }}
      >
        {children}
      </Typography>
    </TreeItemLabel>
  );
}

interface CustomTreeItemProps
  extends
    Omit<UseTreeItemParameters, 'rootRef'>,
    Omit<React.HTMLAttributes<HTMLLIElement>, 'onFocus'> {}

const CustomTreeItem = React.forwardRef(function CustomTreeItem(
  props: CustomTreeItemProps,
  ref: React.Ref<HTMLLIElement>,
) {
  const { id, itemId, label, disabled, children, ...other } = props;

  const {
    getRootProps,
    getContentProps,
    getIconContainerProps,
    getLabelProps,
    getGroupTransitionProps,
    status,
    publicAPI,
  } = useTreeItem({ id, itemId, children, label, disabled, rootRef: ref });

  const item = publicAPI.getItem(itemId);
  const color = item?.color;
  return (
    <TreeItemProvider id={id} itemId={itemId}>
      <TreeItemRoot {...getRootProps(other)}>
        <TreeItemContent
          {...getContentProps({
            className: clsx('content', {
              expanded: status.expanded,
              selected: status.selected,
              focused: status.focused,
              disabled: status.disabled,
            }),
          })}
        >
          {status.expandable && (
            <TreeItemIconContainer {...getIconContainerProps()}>
              <TreeItemIcon status={status} />
            </TreeItemIconContainer>
          )}

          <CustomLabel {...getLabelProps({ color })} />
        </TreeItemContent>
        {children && (
          <TransitionComponent
            {...getGroupTransitionProps({ className: 'groupTransition' })}
          />
        )}
      </TreeItemRoot>
    </TreeItemProvider>
  );
});

export default function CustomizedTreeView({
  summary,
  system,
  coverage,
}: CustomizedTreeViewProps) {
  const items = React.useMemo<TreeViewBaseItem<ExtendedTreeItemProps>[]>(() => {
    const statusColor = (value: number | null | undefined) => {
      if (value === null || value === undefined || Number.isNaN(value)) return undefined;
      return value > 0 ? 'green' : 'blue';
    };

    const boolColor = (value: boolean | undefined) => {
      if (value === undefined) return undefined;
      return value ? 'green' : 'blue';
    };

    const formatBool = (value: boolean | undefined, onLabel: string, offLabel: string) => {
      if (value === undefined) return 'No data';
      return value ? onLabel : offLabel;
    };

    const coverageItems =
      coverage && coverage.length > 0
        ? coverage.map((segment, index) => ({
            id: `coverage-${index}`,
            label: `${segment.label}: ${
              Number.isFinite(segment.value) ? segment.value.toFixed(1) : '0'
            }%`,
            color: segment.value >= 25 ? 'green' : 'blue',
          }))
        : [{ id: 'coverage-empty', label: 'Coverage data unavailable', color: 'blue' }];

    return [
      {
        id: 'field-ops',
        label: 'Field ops',
        children: [
          {
            id: 'field-ops-active',
            label: `Active flights: ${formatNumber(summary?.active_flights)}`,
            color: statusColor(summary?.active_flights),
          },
          {
            id: 'field-ops-24h',
            label: `Flights (24h): ${formatNumber(summary?.flights_24h)}`,
            color: statusColor(summary?.flights_24h),
          },
          {
            id: 'field-ops-hours',
            label: `Survey hours (7d): ${formatHours(summary?.flight_hours_7d)}`,
            color: statusColor(summary?.flight_hours_7d),
          },
        ],
      },
      {
        id: 'telemetry',
        label: 'Telemetry',
        children: [
          {
            id: 'telemetry-frames',
            label: `Telemetry frames (24h): ${formatNumber(summary?.telemetry_24h)}`,
            color: statusColor(summary?.telemetry_24h),
          },
          {
            id: 'telemetry-battery',
            label: `Avg battery health (24h): ${formatNumber(
              summary?.avg_battery_24h,
              '%',
            )}`,
            color:
              summary?.avg_battery_24h !== null &&
              summary?.avg_battery_24h !== undefined
                ? summary.avg_battery_24h >= 50
                  ? 'green'
                  : 'blue'
                : undefined,
          },
        ],
      },
      {
        id: 'system',
        label: 'Systems',
        children: [
          {
            id: 'system-telemetry',
            label: `Telemetry service: ${formatBool(
              system?.telemetry_running,
              'Running',
              'Stopped',
            )}`,
            color: boolColor(system?.telemetry_running),
          },
          {
            id: 'system-mavlink',
            label: `MAVLink: ${formatBool(system?.mavlink_connected, 'Connected', 'Idle')}`,
            color: boolColor(system?.mavlink_connected),
          },
          {
            id: 'system-clients',
            label: `Active clients: ${formatNumber(system?.active_connections)}`,
            color: statusColor(system?.active_connections),
          },
        ],
      },
      {
        id: 'coverage',
        label: 'Coverage',
        children: coverageItems,
      },
    ];
  }, [summary, system, coverage]);

  return (
    <Card
      variant="outlined"
      sx={{ display: 'flex', flexDirection: 'column', gap: '8px', flexGrow: 1 }}
    >
      <CardContent>
        <Typography component="h2" variant="subtitle2">
          System map
        </Typography>
        <RichTreeView
          items={items}
          aria-label="pages"
          multiSelect
          defaultExpandedItems={['field-ops', 'telemetry', 'system']}
          defaultSelectedItems={['field-ops-active']}
          sx={{
            m: '0 -8px',
            pb: '8px',
            height: 'fit-content',
            flexGrow: 1,
            overflowY: 'auto',
          }}
          slots={{ item: CustomTreeItem }}
        />
      </CardContent>
    </Card>
  );
}

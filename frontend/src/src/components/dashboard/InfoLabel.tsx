import { Box, Tooltip } from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";

type InfoLabelProps = {
  label: string;
  info: string;
};

export default function InfoLabel({ label, info }: InfoLabelProps) {
  return (
    <Box component="span" sx={{ display: "inline-flex", alignItems: "center", gap: 0.5 }}>
      <span>{label}</span>
      <Tooltip title={info} placement="top" arrow>
        <Box
          component="span"
          aria-label={`${label} info`}
          onMouseDown={(event) => event.preventDefault()}
          sx={{
            display: "inline-flex",
            alignItems: "center",
            color: "text.secondary",
            cursor: "help",
            lineHeight: 0,
          }}
        >
          <InfoOutlinedIcon sx={{ fontSize: 14 }} />
        </Box>
      </Tooltip>
    </Box>
  );
}

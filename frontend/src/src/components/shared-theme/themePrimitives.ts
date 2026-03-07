import { createTheme, alpha } from '@mui/material/styles';
import type { Shadows } from "@mui/material/styles";
import type { PaletteMode } from "@mui/material/styles";

declare module '@mui/material/Paper' {
  interface PaperPropsVariantOverrides {
    highlighted: true;
  }
}
declare module '@mui/material/styles' {
  interface ColorRange {
    50: string;
    100: string;
    200: string;
    300: string;
    400: string;
    500: string;
    600: string;
    700: string;
    800: string;
    900: string;
  }

  interface PaletteColor extends ColorRange {}

  interface Palette {
    baseShadow: string;
  }
}

const defaultTheme = createTheme();

const customShadows: Shadows = [...defaultTheme.shadows];

export const brand = {
  50: 'hsl(174, 52%, 96%)',
  100: 'hsl(174, 45%, 90%)',
  200: 'hsl(174, 40%, 80%)',
  300: 'hsl(174, 38%, 66%)',
  400: 'hsl(174, 45%, 50%)',
  500: 'hsl(174, 55%, 38%)',
  600: 'hsl(174, 62%, 30%)',
  700: 'hsl(174, 68%, 24%)',
  800: 'hsl(174, 72%, 16%)',
  900: 'hsl(174, 75%, 11%)',
};

export const gray = {
  50: 'hsl(36, 33%, 97%)',
  100: 'hsl(34, 20%, 93%)',
  200: 'hsl(32, 18%, 85%)',
  300: 'hsl(30, 14%, 72%)',
  400: 'hsl(28, 10%, 58%)',
  500: 'hsl(26, 9%, 45%)',
  600: 'hsl(24, 12%, 32%)',
  700: 'hsl(22, 16%, 22%)',
  800: 'hsl(20, 20%, 14%)',
  900: 'hsl(20, 25%, 8%)',
};

export const green = {
  50: 'hsl(145, 60%, 96%)',
  100: 'hsl(145, 55%, 90%)',
  200: 'hsl(145, 45%, 80%)',
  300: 'hsl(145, 40%, 66%)',
  400: 'hsl(145, 45%, 46%)',
  500: 'hsl(145, 55%, 34%)',
  600: 'hsl(145, 60%, 26%)',
  700: 'hsl(145, 65%, 20%)',
  800: 'hsl(145, 70%, 14%)',
  900: 'hsl(145, 75%, 10%)',
};

export const orange = {
  50: 'hsl(40, 100%, 97%)',
  100: 'hsl(38, 95%, 92%)',
  200: 'hsl(36, 85%, 82%)',
  300: 'hsl(34, 75%, 68%)',
  400: 'hsl(32, 70%, 52%)',
  500: 'hsl(30, 80%, 38%)',
  600: 'hsl(28, 85%, 28%)',
  700: 'hsl(26, 85%, 22%)',
  800: 'hsl(24, 90%, 16%)',
  900: 'hsl(22, 90%, 12%)',
};

export const red = {
  50: 'hsl(8, 85%, 96%)',
  100: 'hsl(8, 80%, 90%)',
  200: 'hsl(8, 75%, 80%)',
  300: 'hsl(8, 70%, 66%)',
  400: 'hsl(8, 70%, 52%)',
  500: 'hsl(8, 75%, 40%)',
  600: 'hsl(8, 80%, 30%)',
  700: 'hsl(8, 85%, 22%)',
  800: 'hsl(8, 88%, 16%)',
  900: 'hsl(8, 90%, 12%)',
};

export const getDesignTokens = (mode: PaletteMode) => {
  customShadows[1] =
    mode === 'dark'
      ? 'hsla(220, 30%, 5%, 0.7) 0px 4px 16px 0px, hsla(220, 25%, 10%, 0.8) 0px 8px 16px -5px'
      : 'hsla(220, 30%, 5%, 0.07) 0px 4px 16px 0px, hsla(220, 25%, 10%, 0.07) 0px 8px 16px -5px';

  return {
    palette: {
      mode,
      primary: {
        light: brand[200],
        main: brand[400],
        dark: brand[700],
        contrastText: brand[50],
        ...(mode === 'dark' && {
          contrastText: brand[50],
          light: brand[300],
          main: brand[400],
          dark: brand[700],
        }),
      },
      info: {
        light: brand[100],
        main: brand[300],
        dark: brand[600],
        contrastText: gray[50],
        ...(mode === 'dark' && {
          contrastText: brand[300],
          light: brand[500],
          main: brand[700],
          dark: brand[900],
        }),
      },
      warning: {
        light: orange[300],
        main: orange[400],
        dark: orange[800],
        ...(mode === 'dark' && {
          light: orange[400],
          main: orange[500],
          dark: orange[700],
        }),
      },
      error: {
        light: red[300],
        main: red[400],
        dark: red[800],
        ...(mode === 'dark' && {
          light: red[400],
          main: red[500],
          dark: red[700],
        }),
      },
      success: {
        light: green[300],
        main: green[400],
        dark: green[800],
        ...(mode === 'dark' && {
          light: green[400],
          main: green[500],
          dark: green[700],
        }),
      },
      grey: {
        ...gray,
      },
      divider: mode === 'dark' ? alpha(gray[700], 0.7) : alpha(gray[300], 0.55),
      background: {
        default: 'hsl(36, 33%, 97%)',
        paper: 'hsl(34, 24%, 95%)',
        ...(mode === 'dark' && {
          default: 'hsl(22, 28%, 6%)',
          paper: 'hsl(22, 24%, 8%)',
        }),
      },
      text: {
        primary: gray[800],
        secondary: gray[600],
        warning: orange[400],
        ...(mode === 'dark' && {
          primary: 'hsl(0, 0%, 100%)',
          secondary: gray[300],
        }),
      },
      action: {
        hover: alpha(gray[200], 0.25),
        selected: `${alpha(gray[200], 0.35)}`,
        ...(mode === 'dark' && {
          hover: alpha(gray[700], 0.25),
          selected: alpha(gray[700], 0.35),
        }),
      },
    },
    typography: {
      fontFamily: '"IBM Plex Sans", "Segoe UI", "Helvetica Neue", Arial, sans-serif',
      h1: {
        fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
        fontSize: defaultTheme.typography.pxToRem(48),
        fontWeight: 600,
        lineHeight: 1.1,
        letterSpacing: -0.8,
      },
      h2: {
        fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
        fontSize: defaultTheme.typography.pxToRem(36),
        fontWeight: 600,
        lineHeight: 1.15,
      },
      h3: {
        fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
        fontSize: defaultTheme.typography.pxToRem(30),
        lineHeight: 1.2,
      },
      h4: {
        fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
        fontSize: defaultTheme.typography.pxToRem(24),
        fontWeight: 600,
        lineHeight: 1.25,
      },
      h5: {
        fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
        fontSize: defaultTheme.typography.pxToRem(20),
        fontWeight: 600,
      },
      h6: {
        fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
        fontSize: defaultTheme.typography.pxToRem(18),
        fontWeight: 600,
      },
      subtitle1: {
        fontSize: defaultTheme.typography.pxToRem(18),
      },
      subtitle2: {
        fontSize: defaultTheme.typography.pxToRem(14),
        fontWeight: 500,
      },
      body1: {
        fontSize: defaultTheme.typography.pxToRem(15),
        lineHeight: 1.6,
      },
      body2: {
        fontSize: defaultTheme.typography.pxToRem(14),
        fontWeight: 400,
        lineHeight: 1.6,
      },
      caption: {
        fontSize: defaultTheme.typography.pxToRem(12),
        fontWeight: 500,
        letterSpacing: 0.2,
      },
    },
    shape: {
      borderRadius: 8,
    },
    shadows: customShadows,
  };
};

export const colorSchemes = {
  light: {
    palette: {
      primary: {
        light: brand[200],
        main: brand[400],
        dark: brand[700],
        contrastText: brand[50],
      },
      info: {
        light: brand[100],
        main: brand[300],
        dark: brand[600],
        contrastText: gray[50],
      },
      warning: {
        light: orange[300],
        main: orange[400],
        dark: orange[800],
      },
      error: {
        light: red[300],
        main: red[400],
        dark: red[800],
      },
      success: {
        light: green[300],
        main: green[400],
        dark: green[800],
      },
      grey: {
        ...gray,
      },
      divider: alpha(gray[300], 0.4),
      background: {
        default: 'hsl(36, 33%, 97%)',
        paper: 'hsl(34, 24%, 95%)',
      },
      text: {
        primary: gray[800],
        secondary: gray[600],
        warning: orange[400],
      },
      action: {
        hover: alpha(gray[200], 0.2),
        selected: `${alpha(gray[200], 0.3)}`,
      },
      baseShadow:
        'hsla(26, 25%, 10%, 0.08) 0px 6px 18px 0px, hsla(22, 20%, 12%, 0.12) 0px 14px 26px -12px',
    },
  },
  dark: {
    palette: {
      primary: {
        contrastText: brand[50],
        light: brand[300],
        main: brand[400],
        dark: brand[700],
      },
      info: {
        contrastText: brand[300],
        light: brand[500],
        main: brand[700],
        dark: brand[900],
      },
      warning: {
        light: orange[400],
        main: orange[500],
        dark: orange[700],
      },
      error: {
        light: red[400],
        main: red[500],
        dark: red[700],
      },
      success: {
        light: green[400],
        main: green[500],
        dark: green[700],
      },
      grey: {
        ...gray,
      },
      divider: alpha(gray[700], 0.6),
      background: {
        default: 'hsl(22, 28%, 6%)',
        paper: 'hsl(22, 24%, 8%)',
      },
      text: {
        primary: 'hsl(0, 0%, 100%)',
        secondary: gray[400],
      },
      action: {
        hover: alpha(gray[600], 0.2),
        selected: alpha(gray[600], 0.3),
      },
      baseShadow:
        'hsla(20, 40%, 4%, 0.7) 0px 6px 18px 0px, hsla(20, 35%, 6%, 0.85) 0px 18px 32px -14px',
    },
  },
};

export const typography = {
  fontFamily: '"IBM Plex Sans", "Segoe UI", "Helvetica Neue", Arial, sans-serif',
  h1: {
    fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
    fontSize: defaultTheme.typography.pxToRem(48),
    fontWeight: 600,
    lineHeight: 1.1,
    letterSpacing: -0.8,
  },
  h2: {
    fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
    fontSize: defaultTheme.typography.pxToRem(36),
    fontWeight: 600,
    lineHeight: 1.15,
  },
  h3: {
    fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
    fontSize: defaultTheme.typography.pxToRem(30),
    lineHeight: 1.2,
  },
  h4: {
    fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
    fontSize: defaultTheme.typography.pxToRem(24),
    fontWeight: 600,
    lineHeight: 1.25,
  },
  h5: {
    fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
    fontSize: defaultTheme.typography.pxToRem(20),
    fontWeight: 600,
  },
  h6: {
    fontFamily: '"Space Grotesk", "IBM Plex Sans", sans-serif',
    fontSize: defaultTheme.typography.pxToRem(18),
    fontWeight: 600,
  },
  subtitle1: {
    fontSize: defaultTheme.typography.pxToRem(18),
  },
  subtitle2: {
    fontSize: defaultTheme.typography.pxToRem(14),
    fontWeight: 500,
  },
  body1: {
    fontSize: defaultTheme.typography.pxToRem(15),
    lineHeight: 1.6,
  },
  body2: {
    fontSize: defaultTheme.typography.pxToRem(14),
    fontWeight: 400,
    lineHeight: 1.6,
  },
  caption: {
    fontSize: defaultTheme.typography.pxToRem(12),
    fontWeight: 500,
    letterSpacing: 0.2,
  },
};

export const shape = {
  borderRadius: 8,
};

// @ts-ignore
const defaultShadows: Shadows = [
  'none',
  'var(--template-palette-baseShadow)',
  ...defaultTheme.shadows.slice(2),
];
export const shadows = defaultShadows;

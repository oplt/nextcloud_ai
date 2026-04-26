import { alpha, createTheme, type ThemeOptions } from '@mui/material/styles';

export type ThemeMode = 'dark' | 'light';

// Brand palette (single source of truth for MUI + CSS variables).
const BRAND = {
  bg: '#fffffe',
  headline: '#272343',
  paragraph: '#2d334a',
  button: '#ffd803',
  buttonText: '#272343',
  stroke: '#272343',
  main: '#fffffe',
  highlight: '#ffd803',
  secondary: '#e3f6f5',
  tertiary: '#bae8e8',
} as const;

export const brandPalette = BRAND;

const paletteByMode: Record<ThemeMode, ThemeOptions['palette']> = {
  dark: {
    mode: 'dark',
    primary: {
      main: BRAND.highlight,
      light: '#ffe666',
      dark: '#e6c200',
      contrastText: BRAND.buttonText,
    },
    secondary: {
      main: BRAND.tertiary,
      light: BRAND.secondary,
      dark: '#8fd1d1',
      contrastText: BRAND.headline,
    },
    background: {
      default: BRAND.headline,
      paper: '#1f1c38',
    },
    text: {
      primary: BRAND.bg,
      secondary: BRAND.tertiary,
    },
    divider: alpha(BRAND.bg, 0.14),
    warning: {
      main: BRAND.highlight,
      light: '#ffe666',
      dark: '#e6c200',
      contrastText: BRAND.buttonText,
    },
    success: {
      main: BRAND.tertiary,
      light: BRAND.secondary,
      dark: '#8fd1d1',
      contrastText: BRAND.headline,
    },
    error: {
      main: '#f25f5c',
      light: '#ff8a87',
      dark: '#c84543',
      contrastText: BRAND.bg,
    },
    info: {
      main: BRAND.secondary,
      light: BRAND.bg,
      dark: BRAND.tertiary,
      contrastText: BRAND.headline,
    },
  },
  light: {
    mode: 'light',
    primary: {
      main: BRAND.highlight,
      light: '#ffe666',
      dark: '#e6c200',
      contrastText: BRAND.buttonText,
    },
    secondary: {
      main: BRAND.headline,
      light: BRAND.paragraph,
      dark: '#1a1730',
      contrastText: BRAND.bg,
    },
    background: {
      default: BRAND.bg,
      paper: BRAND.bg,
    },
    text: {
      primary: BRAND.headline,
      secondary: BRAND.paragraph,
    },
    divider: alpha(BRAND.headline, 0.14),
    warning: {
      main: BRAND.highlight,
      light: '#ffe666',
      dark: '#e6c200',
      contrastText: BRAND.buttonText,
    },
    success: {
      main: BRAND.tertiary,
      light: BRAND.secondary,
      dark: '#8fd1d1',
      contrastText: BRAND.headline,
    },
    error: {
      main: '#d94845',
      light: '#f0726f',
      dark: '#ae322f',
      contrastText: BRAND.bg,
    },
    info: {
      main: BRAND.secondary,
      light: BRAND.bg,
      dark: BRAND.tertiary,
      contrastText: BRAND.headline,
    },
  },
};

export function buildAppTheme(mode: ThemeMode) {
  const palette = paletteByMode[mode]!;

  return createTheme({
    palette,
    shape: {
      borderRadius: 5,
    },
    typography: {
      fontFamily: "'Manrope', system-ui, sans-serif",
      button: {
        fontWeight: 800,
        textTransform: 'none',
      },
      h1: { color: BRAND.headline },
      h2: { color: BRAND.headline },
      h3: { color: BRAND.headline },
      h4: { color: BRAND.headline },
      h5: { color: BRAND.headline },
      h6: { color: BRAND.headline },
    },
    components: {
      MuiCssBaseline: {
        styleOverrides: {
          ':root': {
            colorScheme: mode,
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
            border: `1px solid ${palette.divider}`,
            boxShadow:
              mode === 'dark'
                ? '0 14px 36px rgba(39, 35, 67, 0.32)'
                : '0 14px 36px rgba(39, 35, 67, 0.08)',
          },
        },
      },
      MuiCard: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
            borderRadius: 5,
          },
        },
      },
      MuiButton: {
        defaultProps: {
          disableElevation: true,
        },
        styleOverrides: {
          root: {
            minHeight: 42,
            borderRadius: 999,
            fontWeight: 800,
            paddingInline: 16,
          },
          containedPrimary: {
            color: BRAND.buttonText,
            backgroundColor: BRAND.button,
            '&:hover': {
              backgroundColor: '#e6c200',
            },
          },
          outlinedPrimary: {
            color: BRAND.headline,
            borderColor: BRAND.headline,
          },
          textPrimary: {
            color: BRAND.headline,
          },
        },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            borderRadius: 5,
            backgroundColor:
              mode === 'dark'
                ? alpha(BRAND.bg, 0.04)
                : alpha(BRAND.bg, 0.92),
          },
        },
      },
      MuiInputLabel: {
        styleOverrides: {
          root: {
            fontWeight: 700,
          },
        },
      },
      MuiCheckbox: {
        styleOverrides: {
          root: {
            color: mode === 'dark' ? BRAND.tertiary : BRAND.paragraph,
          },
        },
      },
      MuiLink: {
        styleOverrides: {
          root: {
            color: BRAND.headline,
            textDecorationColor: alpha(BRAND.headline, 0.4),
            '&:hover': {
              textDecorationColor: BRAND.highlight,
            },
          },
        },
      },
    },
  });
}

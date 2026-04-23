import { alpha, createTheme, type ThemeOptions } from '@mui/material/styles';

export type ThemeMode = 'dark' | 'light';

const paletteByMode: Record<ThemeMode, ThemeOptions['palette']> = {
  dark: {
    mode: 'dark',
    primary: {
      main: '#00FFAB',
      light: '#6DFFC9',
      dark: '#00CC89',
      contrastText: '#0A0A0A',
    },
    secondary: {
      main: '#DFFFEF',
      light: '#F3FFF9',
      dark: '#9FEBCB',
      contrastText: '#0A0A0A',
    },
    background: {
      default: '#0A0A0A',
      paper: '#141414',
    },
    text: {
      primary: '#FFFFFF',
      secondary: '#C9C9C9',
    },
    divider: alpha('#FFFFFF', 0.14),
    warning: {
      main: '#00FFAB',
      light: '#6DFFC9',
      dark: '#00CC89',
      contrastText: '#0A0A0A',
    },
    success: {
      main: '#00FFAB',
      light: '#6DFFC9',
      dark: '#00CC89',
      contrastText: '#0A0A0A',
    },
    error: {
      main: '#F25F5C',
      light: '#FF8A87',
      dark: '#C84543',
      contrastText: '#FFFFFF',
    },
    info: {
      main: '#C9C9C9',
      light: '#FFFFFF',
      dark: '#9B9B9B',
      contrastText: '#0A0A0A',
    },
  },
  light: {
    mode: 'light',
    primary: {
      main: '#00FFAB',
      light: '#6DFFC9',
      dark: '#00CC89',
      contrastText: '#0A0A0A',
    },
    secondary: {
      main: '#0A0A0A',
      light: '#404040',
      dark: '#000000',
      contrastText: '#FFFFFF',
    },
    background: {
      default: '#FFFFFF',
      paper: '#FFFFFF',
    },
    text: {
      primary: '#0A0A0A',
      secondary: '#404040',
    },
    divider: alpha('#0A0A0A', 0.14),
    warning: {
      main: '#00E198',
      light: '#6DFFC9',
      dark: '#00B97D',
      contrastText: '#0A0A0A',
    },
    success: {
      main: '#00FFAB',
      light: '#6DFFC9',
      dark: '#00CC89',
      contrastText: '#0A0A0A',
    },
    error: {
      main: '#D94845',
      light: '#F0726F',
      dark: '#AE322F',
      contrastText: '#ffffff',
    },
    info: {
      main: '#CFFFEF',
      light: '#F2FFF9',
      dark: '#9FEBCB',
      contrastText: '#0A0A0A',
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
                ? '0 14px 36px rgba(0, 0, 0, 0.26)'
                : '0 14px 36px rgba(10, 10, 10, 0.06)',
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
            color: mode === 'dark' ? '#0A0A0A' : '#0A0A0A',
          },
        },
      },
      MuiOutlinedInput: {
        styleOverrides: {
          root: {
            borderRadius: 5,
            backgroundColor:
              mode === 'dark'
                ? alpha('#FFFFFF', 0.04)
                : alpha('#FFFFFF', 0.92),
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
            color: mode === 'dark' ? '#C9C9C9' : '#404040',
          },
        },
      },
    },
  });
}

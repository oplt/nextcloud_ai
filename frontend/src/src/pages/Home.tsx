import CssBaseline from '@mui/material/CssBaseline';
import Container from '@mui/material/Container';
import AppTheme from '../components/shared-theme/AppTheme';
import AppAppBar from '../components/AppAppBar';
import MainContent from '../components/MainContent';
import Latest from '../components/Latest';
import Footer from '../components/Footer';

export default function Home(props: { disableCustomTheme?: boolean }) {
  return (
    <AppTheme {...props}>
      <CssBaseline enableColorScheme />

      <AppAppBar />
      <Container
        maxWidth="lg"
        component="main"
        sx={{
          display: 'flex',
          flexDirection: 'column',
          pt: { xs: 10, md: 14 },
          pb: { xs: 6, md: 10 },
          gap: 6,
        }}
      >
        <MainContent />
        <Latest />
      </Container>
      <Footer />
    </AppTheme>
  );
}

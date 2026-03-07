import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./output.css";
import "cesium/Build/Cesium/Widgets/widgets.css";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./queryClient";
import { GoogleMapsProvider } from "./utils/googleMaps";



const container = document.getElementById("root");
if (!container) throw new Error('Root element "#root" not found');

const root = createRoot(container);

root.render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <GoogleMapsProvider>
        <App />
      </GoogleMapsProvider>
    </QueryClientProvider>
  </StrictMode>
);

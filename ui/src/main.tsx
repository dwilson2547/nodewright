import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@xyflow/react/dist/style.css";
import "./index.css";
import App from "./App.tsx";
import Render from "./Render.tsx";
import Share from "./Share.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {location.pathname === "/render" ? <Render /> : location.pathname.startsWith("/s/") ? <Share /> : <App />}
  </StrictMode>,
);

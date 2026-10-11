import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@xyflow/react/dist/style.css";
import "./index.css";
import App from "./App.tsx";
import Render from "./Render.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {location.pathname === "/render" ? <Render /> : <App />}
  </StrictMode>,
);

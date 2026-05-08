import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { applyGraphAppearance, loadGraphAppearance } from "./graphAppearance";
import "./styles.css";

applyGraphAppearance(loadGraphAppearance());

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

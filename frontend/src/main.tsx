import React from "react";
import ReactDOM from "react-dom/client";
import { Workspace } from "./app/Workspace";
import "./app/styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Workspace />
  </React.StrictMode>,
);

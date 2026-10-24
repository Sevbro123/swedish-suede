import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { loadPayload } from "./data";
import "./index.css";

loadPayload().then((D) => createRoot(document.getElementById("root")!).render(<StrictMode><App D={D} /></StrictMode>));

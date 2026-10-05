import "./styles/index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";

import { Layout } from "@/components/Layout";
import { ToastProvider } from "@/components/ui/toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import { DemoStatusProvider } from "@/hooks/useDemoStatus";
import { Landing } from "@/pages/Landing";
import { NotFound } from "@/pages/NotFound";
import { RouteError } from "@/pages/RouteError";

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      {
        errorElement: <RouteError />,
        children: [
          { index: true, element: <Landing /> },
          { path: "tour", lazy: async () => ({ Component: (await import("@/pages/Tour")).Tour }) },
          { path: "try", lazy: async () => ({ Component: (await import("@/pages/Try")).Try }) },
          {
            path: "how-it-works",
            lazy: async () => ({ Component: (await import("@/pages/HowItWorks")).HowItWorks }),
          },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
]);

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");

createRoot(root).render(
  <StrictMode>
    <DemoStatusProvider>
      <TooltipProvider delayDuration={150}>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </TooltipProvider>
    </DemoStatusProvider>
  </StrictMode>,
);

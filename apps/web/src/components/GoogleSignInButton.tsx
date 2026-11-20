import { useEffect, useRef } from "react";

/**
 * "Sign in with Google" via Google Identity Services (OAuth 2.0 / OpenID Connect).
 * Google hands back an ID token (`credential`); the page sends it to /auth/google,
 * which verifies it and returns our own JWT.
 */

interface GisCredentialResponse {
  credential: string;
}

interface GisApi {
  accounts: {
    id: {
      initialize(config: { client_id: string; callback: (r: GisCredentialResponse) => void; ux_mode?: "popup" | "redirect" }): void;
      renderButton(parent: HTMLElement, options: Record<string, unknown>): void;
    };
  };
}

declare global {
  interface Window {
    google?: GisApi;
  }
}

const GIS_SRC = "https://accounts.google.com/gsi/client";
let gisLoading: Promise<GisApi> | null = null;

function loadGis(): Promise<GisApi> {
  if (window.google?.accounts?.id) return Promise.resolve(window.google);
  gisLoading ??= new Promise<GisApi>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = GIS_SRC;
    script.async = true;
    script.onload = () => (window.google ? resolve(window.google) : reject(new Error("Google script loaded without API")));
    script.onerror = () => {
      gisLoading = null; // allow a retry (e.g. after coming back online)
      script.remove();
      reject(new Error("Could not load Google sign-in"));
    };
    document.head.appendChild(script);
  });
  return gisLoading;
}

export function GoogleSignInButton({
  clientId,
  locale,
  onCredential,
  onError,
}: {
  clientId: string;
  locale: string;
  onCredential: (credential: string) => void;
  onError: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const handlers = useRef({ onCredential, onError });
  handlers.current = { onCredential, onError };

  useEffect(() => {
    let cancelled = false;
    loadGis()
      .then((google) => {
        const el = ref.current;
        if (cancelled || !el) return;
        google.accounts.id.initialize({
          client_id: clientId,
          ux_mode: "popup",
          callback: (r) => handlers.current.onCredential(r.credential),
        });
        el.replaceChildren();
        google.accounts.id.renderButton(el, {
          theme: "outline",
          size: "large",
          text: "continue_with",
          shape: "rectangular",
          locale,
          width: Math.min(400, Math.max(200, el.offsetWidth || 320)),
        });
      })
      .catch(() => {
        if (!cancelled) handlers.current.onError();
      });
    return () => {
      cancelled = true;
    };
  }, [clientId, locale]);

  return <div ref={ref} className="flex min-h-[44px] w-full justify-center" />;
}

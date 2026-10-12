import { useEffect, useRef } from "react";
import type { CSSProperties, ReactNode } from "react";

interface SpotlightCardProps {
  children: ReactNode;
  className?: string;
  glowHue?: number;
}

export function SpotlightCard({ children, className = "", glowHue = 158 }: SpotlightCardProps) {
  const cardRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const syncPointer = (event: PointerEvent) => {
      const card = cardRef.current;
      if (!card) return;

      card.style.setProperty("--spotlight-x", event.clientX.toFixed(2));
      card.style.setProperty("--spotlight-y", event.clientY.toFixed(2));

      const bounds = card.getBoundingClientRect();
      const isInside = event.clientX >= bounds.left && event.clientX <= bounds.right
        && event.clientY >= bounds.top && event.clientY <= bounds.bottom;

      if (isInside) {
        const tiltY = ((event.clientX - bounds.left) / bounds.width - 0.5) * 5;
        const tiltX = (0.5 - (event.clientY - bounds.top) / bounds.height) * 5;
        card.style.setProperty("--tilt-x", tiltX.toFixed(2));
        card.style.setProperty("--tilt-y", tiltY.toFixed(2));
      } else {
        card.style.setProperty("--tilt-x", "0");
        card.style.setProperty("--tilt-y", "0");
      }
    };

    document.addEventListener("pointermove", syncPointer, { passive: true });
    return () => document.removeEventListener("pointermove", syncPointer);
  }, []);

  return (
    <article
      ref={cardRef}
      className={`pricing-glow-card ${className}`}
      style={{ "--glow-hue": glowHue } as CSSProperties}
    >
      <span className="pricing-glow-aura" aria-hidden="true" />
      {children}
    </article>
  );
}

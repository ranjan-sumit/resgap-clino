"use client";

import { useEffect, useRef } from "react";
import { animate, useMotionValue, useReducedMotion } from "framer-motion";

/** Animates a number counting up from 0 to `value` on mount. Renders into
 * a plain <span> ref (not React state per frame) so the tween doesn't
 * trigger a re-render on every tick. Respects prefers-reduced-motion --
 * jumps straight to the final value instead of animating. Non-numeric
 * values (e.g. "Not recorded") should be rendered as plain text by the
 * caller instead of passed here. */
export function CountUp({
  value,
  formatter = (n: number) => Math.round(n).toLocaleString("en-US"),
  className,
}: {
  value: number;
  formatter?: (n: number) => string;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const motionValue = useMotionValue(0);
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    if (!ref.current) return;
    if (reduceMotion) {
      ref.current.textContent = formatter(value);
      return;
    }
    const controls = animate(motionValue, value, {
      duration: 0.8,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => {
        if (ref.current) ref.current.textContent = formatter(v);
      },
    });
    return () => controls.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- motionValue is stable, formatter is expected inline
  }, [value, reduceMotion]);

  return <span ref={ref} className={className}>{formatter(0)}</span>;
}

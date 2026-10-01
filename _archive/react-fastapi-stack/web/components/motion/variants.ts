import type { Variants } from "framer-motion";

// Shared timing so no two screens invent their own spring/easing curve.
// Tuned once here; every consumer imports rather than re-guessing.

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.28, ease: [0.16, 1, 0.3, 1] } },
};

export const staggerContainer: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.045, delayChildren: 0.02 } },
};

export const springSlide = { type: "spring" as const, stiffness: 500, damping: 40 };

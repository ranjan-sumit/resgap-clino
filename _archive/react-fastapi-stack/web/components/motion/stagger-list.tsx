"use client";

import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { fadeUp, staggerContainer } from "@/components/motion/variants";

/** Generic staggered-reveal wrapper -- each direct child fades/slides in
 * with a small delay after the one before it. Use for card grids/lists
 * (stat rows, gap cards, proposal cards) instead of every screen inventing
 * its own stagger timing. */
export function StaggerList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div initial="hidden" animate="visible" variants={staggerContainer} className={className}>
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div variants={fadeUp} className={className}>
      {children}
    </motion.div>
  );
}

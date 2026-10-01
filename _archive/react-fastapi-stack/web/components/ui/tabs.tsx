"use client"

import * as React from "react"
import * as TabsPrimitive from "@radix-ui/react-tabs"

import { cn } from "@/lib/utils"

const Tabs = TabsPrimitive.Root

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      // Elevated pill to match the app's card language (shadow-card, a real
      // border) instead of the bare shadcn default -- was reported as
      // "plain/flat, no polish" against the rest of the app's design.
      "inline-flex h-10 items-center justify-center gap-0.5 rounded-lg border border-border/60 bg-secondary/70 p-1 text-neutral shadow-card backdrop-blur-sm dark:border-dark-border dark:bg-dark-secondary/70 dark:text-dark-muted-foreground",
      className
    )}
    {...props}
  />
))
TabsList.displayName = TabsPrimitive.List.displayName

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      // Active state now reads as a real raised chip (card shadow + a
      // brand-tinted ring) rather than a near-invisible `shadow-sm`, and
      // the inactive state gets its own hover so the whole bar feels
      // interactive, not just the active tab.
      "inline-flex items-center justify-center whitespace-nowrap rounded-md px-3.5 py-1.5 text-sm font-medium text-neutral/80 transition-all duration-150 hover:text-clinova-deep focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-white data-[state=active]:text-clinova-deep data-[state=active]:shadow-card data-[state=active]:ring-1 data-[state=active]:ring-border/80 dark:text-dark-muted-foreground dark:hover:text-dark-foreground dark:data-[state=active]:bg-dark-card dark:data-[state=active]:text-dark-foreground dark:data-[state=active]:ring-dark-border",
      className
    )}
    {...props}
  />
))
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
      className
    )}
    {...props}
  />
))
TabsContent.displayName = TabsPrimitive.Content.displayName

export { Tabs, TabsList, TabsTrigger, TabsContent }

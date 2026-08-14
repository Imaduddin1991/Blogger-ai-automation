import {
  CalendarClock,
  FileText,
  LayoutDashboard,
  Lightbulb,
  Search,
  Send,
  Settings,
  type LucideIcon,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  description: string;
};

export const navItems: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, description: "Overview of your pipeline" },
  { href: "/ideas", label: "Ideas", icon: Lightbulb, description: "Your blog ideas" },
  { href: "/articles", label: "Articles", icon: FileText, description: "Generated and in-progress articles" },
  { href: "/research", label: "Research", icon: Search, description: "Research summaries and sources" },
  { href: "/scheduler", label: "Scheduler", icon: CalendarClock, description: "Scheduled publishing jobs" },
  { href: "/publishing", label: "Publishing", icon: Send, description: "Publish status and history" },
  { href: "/settings", label: "Settings", icon: Settings, description: "Ollama, blog connection, defaults" },
];

export function isActivePath(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

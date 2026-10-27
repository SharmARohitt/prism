import { ShieldCheck, type LucideProps } from "lucide-react";

export function PrismIcon({ className, ...props }: LucideProps) {
  return <ShieldCheck className={className} {...props} />;
}

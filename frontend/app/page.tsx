import Link from "next/link";

export default function HomePage() {
  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-semibold">Welcome to BAKEZY</h2>
      <p className="text-sm text-slate-600">Start by viewing your products.</p>

      <Link
        href="/products"
        className="inline-flex rounded-lg border px-3 py-2 text-sm hover:bg-slate-100"
      >
        Go to Products →
      </Link>
    </div>
  );
}

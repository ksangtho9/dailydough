"use client";

import React from 'react';
import { Grid2x2PlusIcon, MenuIcon } from 'lucide-react';
import Link from 'next/link';
import { Sheet, SheetContent, SheetFooter } from '@/components/ui/sheet';
import { Button, buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export function FloatingHeader() {
	const [open, setOpen] = React.useState(false);

	const links = [
		{
			label: 'Features',
			href: '#features',
		},
		{
			label: 'Pricing',
			href: '#pricing',
		},
	];

	return (
		<header
			className={cn(
				'sticky top-5 z-50',
				'mx-auto w-full max-w-3xl rounded-lg border border-[#E5D7C5] shadow-lg',
				'bg-[#F4E6D7]/60 supports-[backdrop-filter]:bg-[#F4E6D7]/40 backdrop-blur-lg',
			)}
		>
			<nav className="mx-auto flex items-center justify-between p-1.5">
				<Link href="/" className="hover:bg-amber-50/50 flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 duration-100">
					<Grid2x2PlusIcon className="size-5 text-amber-700" />
					<p className="font-mono text-base font-bold text-slate-900">Bloom</p>
				</Link>
				<div className="hidden items-center gap-1 lg:flex">
					{links.map((link) => (
						<a
							key={link.href}
							className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }), "text-slate-900 hover:text-amber-700 hover:bg-amber-50/50")}
							href={link.href}
						>
							{link.label}
						</a>
					))}
				</div>
				<div className="flex items-center gap-2">
					<Link href="/login">
						<Button size="sm" variant="ghost" className="hidden lg:inline-flex text-slate-900 hover:text-amber-700 hover:bg-amber-50/50">Sign In</Button>
					</Link>
					<Link href="#contact">
						<Button size="sm" className="bg-amber-600 hover:bg-amber-700 text-white">Contact Sales</Button>
					</Link>
					<Sheet open={open} onOpenChange={setOpen}>
						<Button
							size="icon"
							variant="outline"
							onClick={() => setOpen(!open)}
							className="lg:hidden"
						>
							<MenuIcon className="size-4" />
						</Button>
						<SheetContent
							className="bg-[#F4E6D7]/60 supports-[backdrop-filter]:bg-[#F4E6D7]/40 gap-0 backdrop-blur-lg"
							showClose={false}
							side="left"
						>
							<div className="grid gap-y-2 overflow-y-auto px-4 pt-12 pb-5">
								{links.map((link) => (
									<a
										key={link.href}
										className={cn(buttonVariants({
											variant: 'ghost',
											className: 'justify-start',
										}), "text-slate-900 hover:text-amber-700 hover:bg-amber-50/50")}
										href={link.href}
										onClick={() => setOpen(false)}
									>
										{link.label}
									</a>
								))}
							</div>
							<SheetFooter>
								<Link href="/login" className="w-full">
									<Button variant="outline" className="w-full">Sign In</Button>
								</Link>
								<Link href="#contact" className="w-full">
									<Button className="w-full bg-amber-600 hover:bg-amber-700 text-white">Contact Sales</Button>
								</Link>
							</SheetFooter>
						</SheetContent>
					</Sheet>
				</div>
			</nav>
		</header>
	);
}

"use client";

import { Mail, MessageSquare } from "lucide-react";

export function ContactSection() {
  return (
    <section id="contact" className="py-20 md:py-32 bg-white">
      <div className="mx-auto max-w-7xl px-6">
        <div className="mx-auto max-w-2xl text-center mb-12">
          <h2 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
            Get In Touch
          </h2>
          <p className="mt-4 text-lg text-slate-600">
            Have questions? Want to see a demo? We're here to help.
          </p>
        </div>

        <div className="mx-auto max-w-2xl">
          <div className="rounded-2xl border border-amber-100 bg-gradient-to-br from-amber-50/50 to-white p-8 md:p-12">
            <div className="space-y-6">
              <div className="flex items-start gap-4">
                <div className="rounded-lg bg-amber-100 p-3">
                  <Mail className="h-6 w-6 text-amber-600" />
                </div>
                <div>
                  <h3 className="font-semibold text-slate-900 mb-1">Email Us</h3>
                  <a
                    href="mailto:sales@bloom-bakery.com"
                    className="text-amber-600 hover:text-amber-700 transition-colors"
                  >
                    sales@bloom-bakery.com
                  </a>
                </div>
              </div>

              <div className="flex items-start gap-4">
                <div className="rounded-lg bg-emerald-100 p-3">
                  <MessageSquare className="h-6 w-6 text-emerald-600" />
                </div>
                <div>
                  <h3 className="font-semibold text-slate-900 mb-1">Schedule a Demo</h3>
                  <p className="text-slate-600 text-sm">
                    Contact us to schedule a personalized demo and see how Bloom can help your bakery.
                  </p>
                </div>
              </div>
            </div>

            <div className="mt-8 pt-8 border-t border-amber-200">
              <a
                href="mailto:sales@bloom-bakery.com?subject=Interested in Bloom&body=Hello, I'd like to learn more about Bloom and schedule a demo."
                className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-amber-600 px-8 py-4 text-base font-semibold text-white shadow-lg hover:bg-amber-700 transition-all hover:shadow-xl"
              >
                <Mail className="h-5 w-5" />
                Send Us an Email
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

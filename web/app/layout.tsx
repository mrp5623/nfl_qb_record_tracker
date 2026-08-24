import type { Metadata } from "next";
import { Archivo, Barlow_Semi_Condensed } from "next/font/google";
import "./globals.css";

// Barlow Semi Condensed carries the table. Twenty-five stat columns plus a name
// and a record is a lot of horizontal space, and a semi-condensed face fits them
// without shrinking the type to the point of being unreadable. It was drawn for
// signage, which is close to what a scoreboard is.
const barlow = Barlow_Semi_Condensed({
  variable: "--font-table",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

// Archivo for headings and controls: grotesque, slightly editorial, and clearly
// a different voice from the data so chrome never reads as content.
const archivo = Archivo({
  variable: "--font-display",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "QB Records",
  description:
    "Every NFL quarterback season and game since 1999, graded against history and against the field.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${barlow.variable} ${archivo.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}

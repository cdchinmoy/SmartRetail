import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
export function cn(...inputs:ClassValue[]){return twMerge(clsx(inputs));}
const variants=cva('inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2',{variants:{variant:{default:'bg-teal-800 text-white hover:bg-teal-900',outline:'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50'},size:{default:'h-10 px-4',sm:'h-8 px-3'}},defaultVariants:{variant:'default',size:'default'}});
export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>,VariantProps<typeof variants>{asChild?:boolean}
export function Button({className,variant,size,asChild=false,...props}:ButtonProps){const Comp=asChild?Slot:'button';return <Comp className={cn(variants({variant,size,className}))} {...props}/>;}

import React, { useState, useRef } from 'react';
import { createPortal } from 'react-dom';

interface TooltipProps {
    text: string;
}

/**
 * Shared Tooltip Component
 * Uses React Portal and Fixed Positioning to breakout of stacking contexts.
 * Ensures z-index dominance (99999) and visibility (px units).
 */
const Tooltip: React.FC<TooltipProps> = ({ text }) => {
    const [show, setShow] = useState(false);
    const [pos, setPos] = useState({ x: 0, y: 0 });
    const iconRef = useRef<HTMLSpanElement>(null);

    const handleEnter = () => {
        if (iconRef.current) {
            const rect = iconRef.current.getBoundingClientRect();
            setPos({
                x: rect.left + rect.width / 2,
                y: rect.top - 10
            });
            setShow(true);
        }
    };

    return (
        <>
            <span
                ref={iconRef}
                className="material-symbols-outlined text-neutral-600 text-[16px] cursor-help hover:text-white transition-colors ml-2 align-middle select-none"
                onMouseEnter={handleEnter}
                onMouseLeave={() => setShow(false)}
            >
                info
            </span>
            {show && createPortal(
                <div
                    className="fixed z-[99999] px-3 py-2 bg-neutral-900 border border-white/10 rounded-lg text-[10px] text-neutral-300 shadow-2xl pointer-events-none max-w-[200px] text-center leading-tight"
                    style={{
                        left: `${pos.x}px`,
                        top: `${pos.y}px`,
                        transform: 'translate(-50%, -100%)'
                    }}
                >
                    {text}
                    {/* Tail */}
                    <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-neutral-900"></div>
                </div>,
                document.body
            )}
        </>
    );
};

export default Tooltip;

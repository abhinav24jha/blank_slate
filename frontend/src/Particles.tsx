import React, { useEffect, useRef } from "react";

type Props = {
  density?: number;   // particles per 10,000 px²
  maxSpeed?: number;  // px per frame (scaled by DPR)
  size?: number;      // base radius in px
  className?: string;
};

export default function Particles({
  density = 0.12,
  maxSpeed = 0.7,
  size = 1.6,
  className = "",
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d")!;
    let width = 0, height = 0, dpr = Math.max(1, window.devicePixelRatio || 1);

    type P = { x: number; y: number; vx: number; vy: number; r: number };
    let particles: P[] = [];

    const rand = (min: number, max: number) => Math.random() * (max - min) + min;

    const resize = () => {
      const { clientWidth, clientHeight } = canvas.parentElement!;
      width = clientWidth;
      height = clientHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // recompute particle count based on area
      const area = width * height;
      const targetCount = Math.round((area / 10000) * density);
      if (particles.length < targetCount) {
        // add
        for (let i = particles.length; i < targetCount; i++) {
          particles.push({
            x: Math.random() * width,
            y: Math.random() * height,
            vx: rand(-maxSpeed, maxSpeed),
            vy: rand(-maxSpeed, maxSpeed),
            r: rand(size * 0.7, size * 1.3),
          });
        }
      } else if (particles.length > targetCount) {
        particles.length = targetCount;
      }
    };

    const step = () => {
      ctx.clearRect(0, 0, width, height);

      // draw soft vignette of dots
      ctx.fillStyle = "rgba(255,255,255,0.85)";
      for (const p of particles) {
        // move
        p.x += p.vx;
        p.y += p.vy;

        // wrap around edges (seamless)
        if (p.x < -10) p.x = width + 10;
        if (p.x > width + 10) p.x = -10;
        if (p.y < -10) p.y = height + 10;
        if (p.y > height + 10) p.y = -10;

        // draw
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }

      rafRef.current = requestAnimationFrame(step);
    };

    const onResize = () => {
      // debounce a frame
      cancelAnimationFrame(rafRef.current!);
      resize();
      step();
    };

    resize();
    step();
    window.addEventListener("resize", onResize);

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      window.removeEventListener("resize", onResize);
    };
  }, [density, maxSpeed, size]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={`absolute inset-0 pointer-events-none ${className}`}
    />
  );
}

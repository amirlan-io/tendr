import { useEffect, useRef } from "react";

const VERTEX_SHADER = `
  attribute vec2 a_position;
  void main() {
    gl_Position = vec4(a_position, 0.0, 1.0);
  }
`;

// Metaballs share a continuous surface: nearby drops stretch, join and separate.
// The field gradient gives the liquid its rounded lighting without a 3D library.
const FRAGMENT_SHADER = `
  precision mediump float;
  uniform vec2 u_resolution;
  uniform float u_time;

  void main() {
    vec2 uv = gl_FragCoord.xy / u_resolution;
    float aspect = u_resolution.x / u_resolution.y;
    vec2 p = (uv - 0.5) * vec2(aspect, 1.0);
    float t = u_time * 0.4;
    p += 0.035 * vec2(
      sin(p.y * 5.0 + t * 0.65),
      cos(p.x * 4.0 - t * 0.5)
    );

    float field = 0.0;
    vec2 gradient = vec2(0.0);
    for (int i = 0; i < 7; i++) {
      float seed = float(i);
      float phase = seed * 2.39996;
      vec2 center = vec2(
        sin(phase + t * (0.21 + seed * 0.012)) * aspect * 0.46,
        sin(phase * 1.7 + t * (0.3 + seed * 0.018)) * 0.68
      );
      float radius = 0.138 + 0.054 * (0.5 + 0.5 * sin(seed * 3.7));
      radius *= 1.0 + 0.12 * sin(t * 0.5 + phase);
      vec2 delta = p - center;
      float distanceSquared = dot(delta, delta) + 0.003;
      float contribution = radius * radius / distanceSquared;
      field += contribution;
      gradient -= 2.0 * contribution * delta / distanceSquared;
    }

    float surface = smoothstep(0.94, 1.12, field);
    float halo = smoothstep(0.22, 1.2, field);
    vec3 normal = normalize(vec3(-gradient * 0.055, 1.0));
    vec3 light = normalize(vec3(-0.5, 0.8, 1.0));
    float diffuse = max(dot(normal, light), 0.0);
    float rim = pow(1.0 - normal.z, 2.0);
    float sheen = pow(max(dot(reflect(-light, normal), vec3(0.0, 0.0, 1.0)), 0.0), 22.0);

    float flow = 0.5 + 0.5 * sin(p.x * 2.4 + p.y * 3.2 + t * 0.32);
    vec3 navy = vec3(0.018, 0.085, 0.22);
    vec3 emerald = vec3(0.018, 0.25, 0.145);
    vec3 gold = vec3(0.48, 0.37, 0.075);
    vec3 liquid = mix(navy, emerald, smoothstep(0.08, 0.85, flow));
    float warmth = smoothstep(0.65, 0.98,
      0.5 + 0.5 * sin(p.x * 2.0 - p.y * 3.0 - t * 0.22 + 1.7));
    liquid = mix(liquid, gold, warmth * 0.65);
    liquid *= 0.48 + diffuse * 0.8;
    liquid += rim * vec3(0.025, 0.10, 0.075);
    liquid += sheen * vec3(0.12, 0.17, 0.105);

    vec3 backdrop = vec3(0.016, 0.023, 0.032);
    backdrop += halo * mix(navy, emerald, flow) * 0.14;
    vec3 color = mix(backdrop, liquid, surface * 0.88);
    // Keep the centre quiet enough for headings and forms to remain legible.
    float quietCenter = exp(-dot(p * vec2(1.35, 0.8), p * vec2(1.35, 0.8)) * 2.0);
    color *= 1.0 - quietCenter * 0.24;
    float vignette = smoothstep(0.25, 0.9, length(uv - 0.5));
    color *= 1.0 - vignette * 0.4;
    gl_FragColor = vec4(color, 1.0);
  }
`;

export function LavaBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const elapsedRef = useRef(17);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let gl: WebGLRenderingContext | null = null;
    let program: WebGLProgram | null = null;
    let buffer: WebGLBuffer | null = null;
    let resolution: WebGLUniformLocation | null = null;
    let time: WebGLUniformLocation | null = null;
    let frame = 0;
    let previousFrame = 0;
    let elapsed = elapsedRef.current;
    let failed = false;

    function release() {
      if (gl && buffer) gl.deleteBuffer(buffer);
      if (gl && program) gl.deleteProgram(program);
      buffer = null;
      program = null;
    }

    function initialize(): boolean {
      if (program) return true;
      if (failed) return false;
      try {
        gl = canvas!.getContext("webgl", {
          alpha: false,
          antialias: false,
          depth: false,
          stencil: false,
          powerPreference: "low-power",
        });
        if (!gl) {
          failed = true;
          return false;
        }
        const context = gl;
        const compile = (type: number, source: string) => {
          const shader = context.createShader(type);
          if (!shader) return null;
          context.shaderSource(shader, source);
          context.compileShader(shader);
          if (!context.getShaderParameter(shader, context.COMPILE_STATUS)) {
            context.deleteShader(shader);
            return null;
          }
          return shader;
        };
        const vertex = compile(gl.VERTEX_SHADER, VERTEX_SHADER);
        const fragment = compile(gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
        program = gl.createProgram();
        if (!vertex || !fragment || !program) {
          if (vertex) gl.deleteShader(vertex);
          if (fragment) gl.deleteShader(fragment);
          throw new Error("Background shader unavailable");
        }
        gl.attachShader(program, vertex);
        gl.attachShader(program, fragment);
        gl.linkProgram(program);
        gl.deleteShader(vertex);
        gl.deleteShader(fragment);
        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
          throw new Error("Background shader unavailable");
        }
        gl.useProgram(program);
        buffer = gl.createBuffer();
        if (!buffer) throw new Error("Background buffer unavailable");
        gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
        const position = gl.getAttribLocation(program, "a_position");
        gl.enableVertexAttribArray(position);
        gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
        resolution = gl.getUniformLocation(program, "u_resolution");
        time = gl.getUniformLocation(program, "u_time");
        return true;
      } catch {
        failed = true;
        release();
        return false;
      }
    }

    function draw() {
      if (!gl || !program) return;
      gl.uniform2f(resolution, canvas!.width, canvas!.height);
      gl.uniform1f(time, elapsed);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      canvas!.dataset.ready = "true";
    }

    function resize() {
      if (!gl || !program) return;
      const width = Math.max(1, window.innerWidth);
      const height = Math.max(1, window.innerHeight);
      // Decorative liquid needs no retina resolution; cap GPU work on large screens.
      const scale = Math.min(1, Math.sqrt(650_000 / (width * height)));
      canvas!.width = Math.max(1, Math.round(width * scale));
      canvas!.height = Math.max(1, Math.round(height * scale));
      gl.viewport(0, 0, canvas!.width, canvas!.height);
      draw();
    }

    function animate(now: number) {
      if (now - previousFrame >= 1000 / 30) {
        elapsed += previousFrame ? Math.min((now - previousFrame) / 1000, 0.1) : 0;
        previousFrame = now;
        draw();
      }
      frame = window.requestAnimationFrame(animate);
    }

    function sync() {
      window.cancelAnimationFrame(frame);
      previousFrame = 0;
      if (document.hidden || !document.documentElement.classList.contains("dark")) return;
      if (!initialize()) return;
      resize();
      frame = window.requestAnimationFrame(animate);
    }

    function onContextLost(event: Event) {
      event.preventDefault();
      window.cancelAnimationFrame(frame);
      failed = true;
      delete canvas!.dataset.ready;
    }

    function onContextRestored() {
      release();
      failed = false;
      sync();
    }

    const themeObserver = new MutationObserver(sync);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    document.addEventListener("visibilitychange", sync);
    window.addEventListener("resize", resize);
    canvas.addEventListener("webglcontextlost", onContextLost);
    canvas.addEventListener("webglcontextrestored", onContextRestored);
    sync();

    return () => {
      elapsedRef.current = elapsed;
      window.cancelAnimationFrame(frame);
      themeObserver.disconnect();
      document.removeEventListener("visibilitychange", sync);
      window.removeEventListener("resize", resize);
      canvas.removeEventListener("webglcontextlost", onContextLost);
      canvas.removeEventListener("webglcontextrestored", onContextRestored);
      delete canvas.dataset.ready;
      release();
    };
  }, []);

  return (
    <div className="lava-background" aria-hidden="true">
      <canvas ref={canvasRef} className="lava-background__canvas" />
    </div>
  );
}

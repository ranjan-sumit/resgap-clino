import { ImageResponse } from "next/og";
import theme from "../../../packages/branding/theme.json";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

// A real branded favicon (generated, not Next's default), matching the
// exact sidebar logo mark -- solid brand-blue tile + white "C" -- so the
// browser tab carries the brand instead of a generic Next.js icon.
export default function Icon() {
  const { clinova_blue } = theme.colors;
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          borderRadius: 7,
          background: clinova_blue,
        }}
      >
        <div
          style={{
            fontFamily: "sans-serif",
            fontWeight: 600,
            fontSize: 20,
            color: "white",
            lineHeight: 1,
          }}
        >
          C
        </div>
      </div>
    ),
    { ...size },
  );
}

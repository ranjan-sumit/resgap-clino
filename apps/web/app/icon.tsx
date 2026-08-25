import { ImageResponse } from "next/og";
import theme from "../../../packages/branding/theme.json";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

// A real branded favicon (generated, not Next's default), matching the
// exact sidebar logo mark -- gradient badge + "C" -- so the browser tab
// carries the brand instead of a generic Next.js icon.
export default function Icon() {
  const { clinova_cyan, clinova_light_blue, clinova_deep_blue } = theme.colors;
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
          background: `linear-gradient(135deg, ${clinova_cyan} 0%, ${clinova_light_blue} 100%)`,
        }}
      >
        <div
          style={{
            fontFamily: "serif",
            fontSize: 20,
            color: clinova_deep_blue,
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

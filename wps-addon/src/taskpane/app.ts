import "./styles.css";
import { initializeApp, runFormatPreview, runProofread } from "./ui/actions";

const buttons = document.querySelectorAll<HTMLButtonElement>("#actions button");

buttons[0]?.addEventListener("click", () => {
  void runProofread();
});

buttons[1]?.addEventListener("click", () => {
  void runFormatPreview();
});

void initializeApp();

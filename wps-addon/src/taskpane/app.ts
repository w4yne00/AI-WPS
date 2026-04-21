import "./styles.css";
import { applyPreview, initializeApp, runFormatPreview, runProofread, runRewrite } from "./ui/actions";

const buttons = document.querySelectorAll<HTMLButtonElement>("#actions button");
const applyButton = document.getElementById("apply-button");

buttons[0]?.addEventListener("click", () => {
  void runProofread();
});

buttons[1]?.addEventListener("click", () => {
  void runFormatPreview();
});

buttons[2]?.addEventListener("click", () => {
  void runRewrite();
});

applyButton?.addEventListener("click", () => {
  applyPreview();
});

void initializeApp();

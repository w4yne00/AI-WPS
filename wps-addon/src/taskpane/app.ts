import "./styles.css";
import { initializeApp, runProofread } from "./ui/actions";

const buttons = document.querySelectorAll<HTMLButtonElement>("#actions button");

buttons[0]?.addEventListener("click", () => {
  void runProofread();
});

void initializeApp();

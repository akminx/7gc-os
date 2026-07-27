import { useEffect, useState } from "react";

/**
 * Light or dark, chosen from the use scene rather than from habit.
 *
 * The scene is an audit partner at a desk, often beside the printed workbook
 * they are reconciling against, so the default is the operating system's answer
 * and the page follows it. The override exists because the other half of this
 * scene is a review session on a screen shared into a dim room, and because a
 * design that claims both themes work has to be checkable in both without
 * changing the machine's settings.
 *
 * Not a sun-and-moon switch: three named states, one of which is "whatever this
 * machine says". A two-state toggle cannot express the third, so it silently
 * pins the page to one theme the moment it is touched.
 */

export type ThemeChoice = "system" | "light" | "dark";

const STORAGE_KEY = "7gc-theme";
const CHOICES: { id: ThemeChoice; label: string }[] = [
  { id: "system", label: "system" },
  { id: "light", label: "light" },
  { id: "dark", label: "dark" },
];

function stored(): ThemeChoice {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "light" || saved === "dark" || saved === "system") return saved;
  } catch {
    // A browser that refuses storage still gets a working page.
  }
  return "system";
}

export function apply(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

export function ThemeChoiceControl() {
  const [choice, setChoice] = useState<ThemeChoice>(stored);

  useEffect(() => {
    apply(choice);
    try {
      window.localStorage.setItem(STORAGE_KEY, choice);
    } catch {
      // Nothing to recover: the page is already in the chosen theme.
    }
  }, [choice]);

  return (
    <fieldset className="theme">
      <legend className="vh">Colour theme</legend>
      {CHOICES.map((option) => (
        <button
          key={option.id}
          type="button"
          className={option.id === choice ? "theme__opt theme__opt--on" : "theme__opt"}
          aria-pressed={option.id === choice}
          onClick={() => {
            setChoice(option.id);
          }}
        >
          {option.label}
        </button>
      ))}
    </fieldset>
  );
}

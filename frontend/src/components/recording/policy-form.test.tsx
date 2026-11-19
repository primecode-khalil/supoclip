import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PolicyForm } from "./policy-form";
import { DEFAULT_POLICY } from "./types";

it("saves edited settings while preserving fields not exposed by the form", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<PolicyForm policy={{ ...DEFAULT_POLICY, processing_mode: "quality", max_clips_per_window: 8 }} connections={[]} connectionError={null} onSave={save} />);
  fireEvent.change(screen.getByLabelText("Minimum clip score"), { target: { value: "82" } });
  fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ min_score: 82, processing_mode: "quality", max_clips_per_window: 8 })));
});

it("keeps unsaved edits when a polling update arrives", () => {
  const save = vi.fn();
  const { rerender } = render(<PolicyForm policy={DEFAULT_POLICY} connections={[]} connectionError={null} onSave={save} />);
  fireEvent.change(screen.getByLabelText("Minimum clip score"), { target: { value: "90" } });
  rerender(<PolicyForm policy={{ ...DEFAULT_POLICY }} connections={[]} connectionError={null} onSave={save} />);
  expect(screen.getByLabelText("Minimum clip score")).toHaveValue(90);
});

it("validates overlapping windows before submitting", async () => {
  const save = vi.fn();
  render(<PolicyForm policy={DEFAULT_POLICY} connections={[]} connectionError={null} onSave={save} />);
  fireEvent.change(screen.getByLabelText("Segment length (seconds)"), { target: { value: "60" } });
  fireEvent.change(screen.getByLabelText("Overlap (seconds)"), { target: { value: "90" } });
  fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Overlap must be shorter than the segment");
  expect(save).not.toHaveBeenCalled();
});

it("surfaces failed saves and preserves the draft for retry", async () => {
  render(<PolicyForm policy={DEFAULT_POLICY} connections={[]} connectionError={null} onSave={vi.fn().mockRejectedValue(new Error("Recorder is temporarily unavailable"))} />);
  fireEvent.change(screen.getByLabelText("Minimum clip score"), { target: { value: "80" } });
  fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Recorder is temporarily unavailable");
  expect(screen.getByLabelText("Minimum clip score")).toHaveValue(80);
});

it("requires public visibility when Instagram is selected", async () => {
  const save = vi.fn();
  const instagram = { id: "instagram-one", provider: "instagram", display_name: "Demo Reels", username: null, status: "active" } as const;
  render(<PolicyForm policy={DEFAULT_POLICY} connections={[instagram as never]} connectionError={null} onSave={save} />);
  fireEvent.click(screen.getByRole("checkbox", { name: /Demo Reels/ }));
  fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Instagram requires Public visibility");
  expect(save).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Publication visibility"), { target: { value: "public" } });
  fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ publish_privacy: "public", social_account_ids: ["instagram-one"] })));
});

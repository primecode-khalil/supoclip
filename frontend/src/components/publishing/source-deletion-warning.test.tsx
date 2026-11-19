import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SourceDeletionWarning } from "./source-deletion-warning";
afterEach(() => vi.unstubAllGlobals());
it("requires a specific acknowledgement after showing linked YouTube uploads", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ affected:[{id:"post",title:"A scheduled Short",destination:"Demo channel",external_post_id:"video"}],published_retained:1 })));
  const ready = vi.fn();
  render(<SourceDeletionWarning taskIds={["source"]} onReady={ready} />);
  expect(await screen.findByText(/A scheduled Short/)).toBeVisible();
  expect(screen.getByText(/permanently removed from YouTube/i)).toBeVisible();
  expect(ready).toHaveBeenLastCalledWith(false);
  fireEvent.click(screen.getByLabelText("Delete the linked YouTube uploads too"));
  expect(ready).toHaveBeenLastCalledWith(true);
  expect(screen.getByText(/already published/i)).toBeVisible();
});
it("blocks deletion on a failed impact check and recovers on Retry", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(Response.json({}, {status:503})).mockResolvedValue(Response.json({affected:[],published_retained:0})));
  const ready = vi.fn();
  render(<SourceDeletionWarning taskIds={["source"]} onReady={ready} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/could not check/i);
  expect(ready).toHaveBeenLastCalledWith(false);
  fireEvent.click(screen.getByRole("button",{name:"Retry check"}));
  await waitFor(() => expect(ready).toHaveBeenLastCalledWith(true));
});
it("resets acknowledgement when the selected source changes", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({affected:[{id:"post",title:"Linked clip"}],published_retained:0})));
  const ready = vi.fn();
  const {rerender} = render(<SourceDeletionWarning taskIds={["one"]} onReady={ready} />);
  fireEvent.click(await screen.findByLabelText("Delete the linked YouTube uploads too"));
  expect(ready).toHaveBeenLastCalledWith(true);
  rerender(<SourceDeletionWarning taskIds={["two"]} onReady={ready} />);
  await waitFor(() => expect(ready).toHaveBeenLastCalledWith(false));
});

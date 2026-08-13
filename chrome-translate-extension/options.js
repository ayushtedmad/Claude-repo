const input = document.getElementById("apiKey");
const savedLabel = document.getElementById("saved");

chrome.storage.sync.get("apiKey", ({ apiKey }) => {
  if (apiKey) input.value = apiKey;
});

document.getElementById("save").addEventListener("click", () => {
  chrome.storage.sync.set({ apiKey: input.value.trim() }, () => {
    savedLabel.textContent = "Saved!";
    setTimeout(() => (savedLabel.textContent = ""), 1500);
  });
});

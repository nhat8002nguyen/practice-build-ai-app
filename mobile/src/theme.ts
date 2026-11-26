import { StyleSheet } from "react-native";

export const colors = {
  background: "#f5f6f8",
  surface: "#ffffff",
  border: "#d9dce1",
  text: "#1b1f24",
  muted: "#5f6b7a",
  primary: "#2457d6",
  danger: "#c0392b",
  success: "#1e8449",
  warningBackground: "#fff4d6",
  warningBorder: "#e0b100",
};

export const shared = StyleSheet.create({
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    backgroundColor: colors.surface,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 16,
    color: colors.text,
  },
  label: { fontSize: 14, fontWeight: "600", color: colors.text, marginBottom: 4 },
  error: { color: colors.danger, marginVertical: 8 },
  muted: { color: colors.muted, fontSize: 12 },
});

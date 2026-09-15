//
// File: ContentView.swift
// Summary: Manages server setup, connection recovery, and navigation for the iPhone application.
// Modified by: Eric Freeman
// Last modified: 2026-09-15
//

import SwiftUI

/// Presents either the connected finance application or first-run server setup.
struct ContentView: View {
    @AppStorage("serverAddress") private var serverAddress = ""
    @State private var isShowingSettings = false
    @State private var reloadIdentifier = UUID()
    @State private var loadError: String?

    /// Converts the saved address into the URL displayed by the web view.
    private var serverURL: URL? {
        normalizedServerURL(from: serverAddress)
    }

    /// The root user interface and its native navigation controls.
    var body: some View {
        NavigationStack {
            Group {
                if let serverURL {
                    ZStack {
                        FinanceWebView(url: serverURL, loadError: $loadError)
                            .id(reloadIdentifier)

                        if let loadError {
                            ConnectionErrorView(message: loadError) {
                                self.loadError = nil
                                reloadIdentifier = UUID()
                            }
                        }
                    }
                } else {
                    FirstRunView {
                        isShowingSettings = true
                    }
                }
            }
            .navigationTitle("Personal Finance")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItemGroup(placement: .navigationBarTrailing) {
                    if serverURL != nil {
                        Button {
                            loadError = nil
                            reloadIdentifier = UUID()
                        } label: {
                            Label("Reload", systemImage: "arrow.clockwise")
                        }
                    }

                    Button {
                        isShowingSettings = true
                    } label: {
                        Label("Settings", systemImage: "gearshape")
                    }
                }
            }
            .sheet(isPresented: $isShowingSettings) {
                ServerSettingsView(savedAddress: $serverAddress)
            }
        }
    }
}

/// Displays guidance before a Tailscale server URL has been saved.
private struct FirstRunView: View {
    let configure: () -> Void

    /// The first-run explanation and setup action.
    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: "checklist")
                .font(.system(size: 52))
                .foregroundStyle(.tint)
            Text("Connect Personal Finance")
                .font(.title2.bold())
            Text("Enter the private Tailscale URL printed by the macOS installer.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            Button("Set Up Connection", action: configure)
                .buttonStyle(.borderedProminent)
        }
        .padding(28)
    }
}

/// Displays a recoverable web connection failure over the browser content.
private struct ConnectionErrorView: View {
    let message: String
    let retry: () -> Void

    /// The connection error explanation and retry action.
    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: "wifi.exclamationmark")
                .font(.system(size: 52))
                .foregroundStyle(.tint)
            Text("Unable to Connect")
                .font(.title2.bold())
            Text("\(message)\n\nConfirm that Tailscale is connected on both devices. Disconnect Bitdefender VPN if it conflicts.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            Button("Try Again", action: retry)
                .buttonStyle(.borderedProminent)
        }
        .padding(28)
        .background(.background)
    }
}

/// Allows the user to validate and persist the Mac's private Tailscale URL.
private struct ServerSettingsView: View {
    @Binding private var savedAddress: String
    @Environment(\.dismiss) private var dismiss
    @State private var address: String
    @State private var validationMessage: String?

    /// Creates a settings view initialized from the currently saved address.
    /// - Parameter savedAddress: A binding to the persisted server address that is updated on save.
    init(savedAddress: Binding<String>) {
        _savedAddress = savedAddress
        _address = State(initialValue: savedAddress.wrappedValue)
    }

    /// The server-address form and save controls.
    var body: some View {
        NavigationStack {
            Form {
                Section("Tailscale server") {
                    TextField("http://100.x.y.z:5050", text: $address)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)

                    Text("Use the private URL printed by the Personal Finance macOS installer.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)

                    if let validationMessage {
                        Text(validationMessage)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Connection Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        saveAddress()
                    }
                }
            }
        }
    }

    /// Validates, normalizes, and saves the entered server address before closing settings.
    private func saveAddress() {
        guard let url = normalizedServerURL(from: address) else {
            validationMessage = "Enter a valid HTTP or HTTPS Tailscale address."
            return
        }

        savedAddress = url.absoluteString
        dismiss()
    }
}

/// Normalizes a user-entered server address and supplies the default Personal Finance port.
/// - Parameter input: The address entered by the user, with or without a URL scheme or port.
/// - Returns: A validated HTTP or HTTPS URL, or `nil` when the input is not a usable server address.
private func normalizedServerURL(from input: String) -> URL? {
    let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else {
        return nil
    }

    let address = trimmed.contains("://") ? trimmed : "http://\(trimmed)"
    guard var components = URLComponents(string: address),
          let scheme = components.scheme?.lowercased(),
          ["http", "https"].contains(scheme),
          components.host != nil else {
        return nil
    }

    components.scheme = scheme
    if components.port == nil && scheme == "http" {
        components.port = 5050
    }
    return components.url
}

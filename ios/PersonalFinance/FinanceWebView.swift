//
// File: FinanceWebView.swift
// Summary: Hosts the Tailscale-only Personal Finance website inside a native WKWebView.
// Modified by: Eric Freeman
// Last modified: 2026-09-15
//

import Foundation
import SwiftUI
import WebKit

/// Bridges `WKWebView` into SwiftUI and reports navigation failures to the native interface.
struct FinanceWebView: UIViewRepresentable {
    let url: URL
    @Binding var loadError: String?

    /// Creates the navigation delegate that relays browser events to SwiftUI.
    /// - Returns: A coordinator associated with this representable instance.
    func makeCoordinator() -> Coordinator {
        Coordinator(serverURL: url, loadError: $loadError)
    }

    /// Creates and configures the web view used to display Personal Finance.
    /// - Parameter context: SwiftUI context containing the coordinator for this representable.
    /// - Returns: A configured web view with its initial request in progress.
    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.load(URLRequest(url: url))
        return webView
    }

    /// Loads a changed server URL into an existing web view.
    /// - Parameters:
    ///   - webView: The existing web view managed by SwiftUI.
    ///   - context: SwiftUI update context containing the coordinator's previously loaded server URL.
    func updateUIView(_ webView: WKWebView, context: Context) {
        guard context.coordinator.serverURL != url else {
            return
        }
        context.coordinator.serverURL = url
        webView.load(URLRequest(url: url))
    }

    /// Coordinates navigation completion, failures, and links requesting a new browser window.
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        var serverURL: URL
        @Binding private var loadError: String?

        /// Creates a coordinator that can update the SwiftUI connection state.
        /// - Parameters:
        ///   - serverURL: The root server URL currently loaded by the representable.
        ///   - loadError: A binding receiving a user-readable navigation failure message.
        init(serverURL: URL, loadError: Binding<String?>) {
            self.serverURL = serverURL
            _loadError = loadError
        }

        /// Clears any prior error after the requested page finishes loading.
        /// - Parameters:
        ///   - webView: The web view that completed navigation.
        ///   - navigation: The navigation object that completed, when supplied by WebKit.
        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            loadError = nil
        }

        /// Reports a navigation failure that occurs after a request begins.
        /// - Parameters:
        ///   - webView: The web view whose navigation failed.
        ///   - navigation: The failed navigation object, when supplied by WebKit.
        ///   - error: The underlying networking or navigation error.
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            report(error)
        }

        /// Reports a failure that prevents provisional navigation from completing.
        /// - Parameters:
        ///   - webView: The web view whose provisional navigation failed.
        ///   - navigation: The failed provisional navigation object, when supplied by WebKit.
        ///   - error: The underlying networking or navigation error.
        func webView(
            _ webView: WKWebView,
            didFailProvisionalNavigation navigation: WKNavigation!,
            withError error: Error
        ) {
            report(error)
        }

        /// Keeps links that request a new window inside the application's existing web view.
        /// - Parameters:
        ///   - webView: The web view requesting another browser window.
        ///   - configuration: The configuration proposed for the new browser window.
        ///   - navigationAction: The navigation action containing the destination URL.
        ///   - windowFeatures: Requested presentation features for the new browser window.
        /// - Returns: Always `nil` because the request is loaded in the existing web view.
        func webView(
            _ webView: WKWebView,
            createWebViewWith configuration: WKWebViewConfiguration,
            for navigationAction: WKNavigationAction,
            windowFeatures: WKWindowFeatures
        ) -> WKWebView? {
            if navigationAction.targetFrame == nil, let destination = navigationAction.request.url {
                webView.load(URLRequest(url: destination))
            }
            return nil
        }

        /// Publishes a localized navigation error to the SwiftUI error overlay.
        /// - Parameter error: The networking or WebKit failure to present to the user.
        private func report(_ error: Error) {
            guard (error as? URLError)?.code != .cancelled else {
                return
            }
            loadError = error.localizedDescription
        }
    }
}

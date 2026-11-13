package com.example.ui.screens

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.view.View
import android.view.ViewGroup
import android.webkit.RenderProcessGoneDetail
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import com.example.ui.MainViewModel
import com.example.ui.components.borderStroke
import com.example.ui.theme.*

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun WebScreen(
    viewModel: MainViewModel,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    var webViewInstance by remember { mutableStateOf<WebView?>(null) }
    var pageProgress by remember { mutableStateOf(100) }
    var pendingCsvContent by remember { mutableStateOf<String?>(null) }

    val csvSaveLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.CreateDocument("text/csv")
    ) { uri ->
        val content = pendingCsvContent
        pendingCsvContent = null
        if (uri != null && content != null) {
            try {
                context.contentResolver.openOutputStream(uri)?.use { out ->
                    out.write(content.toByteArray(Charsets.UTF_8))
                }
                viewModel.postNotification("Statement CSV saved to device!", true)
            } catch (e: Exception) {
                viewModel.postNotification("Failed to save statement: ${e.message}", false)
            }
        }
    }

    BackHandler(enabled = webViewInstance?.canGoBack() == true) {
        webViewInstance?.goBack()
    }

    val wallet by viewModel.wallet.collectAsState()
    val backendUrl by viewModel.backendUrl.collectAsState()
    val backendStatus by viewModel.backendConnectionStatus.collectAsState()

    LaunchedEffect(wallet?.availableBalance) {
        val bal = ((wallet?.availableBalance ?: 5020000L) / 100.0)
        webViewInstance?.evaluateJavascript(
            "if (window.updateBridgeBalance) { window.updateBridgeBalance($bal); }",
            null
        )
    }

    LaunchedEffect(backendUrl) {
        val escapedUrl = backendUrl.replace("\\", "\\\\").replace("'", "\\'")
        val escapedUid = viewModel.getServerUserId().replace("\\", "\\\\").replace("'", "\\'")
        val escapedName = (viewModel.activeUser.value?.username ?: "Rahul_Player").replace("\\", "\\\\").replace("'", "\\'")
        webViewInstance?.evaluateJavascript(
            "if (window.updateBridgeBackendUrl) { window.updateBridgeBackendUrl('$escapedUrl', '$escapedUid', '$escapedName'); }",
            null
        )
    }

    LaunchedEffect(Unit) {
        viewModel.latestServerPushEvent.collect { ev ->
            val escapedType = ev.eventType.replace("\\", "\\\\").replace("'", "\\'")
            webViewInstance?.evaluateJavascript(
                "if (window.onAndroidServerPush) { window.onAndroidServerPush('$escapedType'); }",
                null
            )
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .background(ObsidianBg)
    ) {
        // Web Control Bar
        Surface(
            color = SurfaceDark,
            border = borderStroke(1.dp, CardBorder),
            modifier = Modifier.fillMaxWidth()
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Default.Language,
                        contentDescription = "Web Version",
                        tint = GoldAccent,
                        modifier = Modifier.size(20.dp)
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    Column {
                        Text(
                            text = "Web Version (Unified Wallet)",
                            color = TextPrimary,
                            fontWeight = FontWeight.Bold,
                            fontSize = 13.sp
                        )
                        Text(
                            text = "Synced: ₹${"%.2f".format((wallet?.availableBalance ?: 5020000L) / 100.0)} • $backendStatus",
                            color = if (backendStatus == "SSE LIVE") NeonGreen else ElectricCyan,
                            fontSize = 10.sp
                        )
                    }
                }

                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconButton(
                        onClick = { webViewInstance?.reload() },
                        modifier = Modifier.size(32.dp)
                    ) {
                        Icon(
                            imageVector = Icons.Default.Refresh,
                            contentDescription = "Reload Web",
                            tint = TextSecondary,
                            modifier = Modifier.size(18.dp)
                        )
                    }

                    Spacer(modifier = Modifier.width(4.dp))

                    OutlinedButton(
                        onClick = {
                            viewModel.postNotification("Standalone Web file located in /web/index.html & assets/web/index.html for deployment!", true)
                        },
                        shape = RoundedCornerShape(8.dp),
                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp),
                        border = borderStroke(1.dp, GoldAccent.copy(alpha = 0.5f)),
                        modifier = Modifier.height(28.dp)
                    ) {
                        Text(
                            text = "📁 Deployable",
                            color = GoldAccent,
                            fontSize = 10.sp,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
            }
        }

        // Loading bar if page is loading
        if (pageProgress < 100) {
            LinearProgressIndicator(
                progress = { pageProgress / 100f },
                color = GoldAccent,
                trackColor = SurfaceDark,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(2.dp)
            )
        }

        DisposableEffect(Unit) {
            onDispose {
                try {
                    webViewInstance?.stopLoading()
                    (webViewInstance?.parent as? ViewGroup)?.removeView(webViewInstance)
                    webViewInstance?.destroy()
                    webViewInstance = null
                } catch (_: Exception) {}
            }
        }

        // Full Screen Responsive Web View
        AndroidView(
            modifier = Modifier
                .fillMaxSize()
                .weight(1f),
            factory = { ctx ->
                WebView(ctx).apply {
                    // Use software rendering to avoid GPU context loss crashes in cloud/emulator environments
                    setLayerType(View.LAYER_TYPE_SOFTWARE, null)

                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    settings.loadWithOverviewMode = true
                    settings.useWideViewPort = true
                    settings.builtInZoomControls = false
                    settings.displayZoomControls = false
                    settings.mediaPlaybackRequiresUserGesture = false
                    settings.allowFileAccess = true
                    @Suppress("DEPRECATION")
                    settings.allowFileAccessFromFileURLs = true
                    @Suppress("DEPRECATION")
                    settings.allowUniversalAccessFromFileURLs = true
                    settings.mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_ALWAYS_ALLOW

                    // Two-way native Android wallet & statement bridge
                    addJavascriptInterface(
                        AndroidWalletBridge(
                            viewModel = viewModel,
                            onDownloadCsv = { filename, csvContent ->
                                post {
                                    pendingCsvContent = csvContent
                                    csvSaveLauncher.launch(filename)
                                }
                            }
                        ),
                        "AndroidBridge"
                    )

                    webChromeClient = object : WebChromeClient() {
                        override fun onProgressChanged(view: WebView?, newProgress: Int) {
                            pageProgress = newProgress
                        }
                    }

                    webViewClient = object : WebViewClient() {
                        override fun onPageFinished(view: WebView?, url: String?) {
                            pageProgress = 100
                            val bal = ((viewModel.wallet.value?.availableBalance ?: 5020000L) / 100.0)
                            val escapedUrl = viewModel.backendUrl.value.replace("\\", "\\\\").replace("'", "\\'")
                            val escapedUid = viewModel.getServerUserId().replace("\\", "\\\\").replace("'", "\\'")
                            val escapedName = (viewModel.activeUser.value?.username ?: "Rahul_Player").replace("\\", "\\\\").replace("'", "\\'")
                            evaluateJavascript(
                                "if (window.updateBridgeBackendUrl) { window.updateBridgeBackendUrl('$escapedUrl', '$escapedUid', '$escapedName'); } if (window.updateBridgeBalance) { window.updateBridgeBalance($bal); }",
                                null
                            )
                        }

                        override fun onRenderProcessGone(
                            view: WebView?,
                            detail: RenderProcessGoneDetail?
                        ): Boolean {
                            // CRITICAL: Return true so aw_browser_terminator does NOT kill the host app
                            try {
                                view?.let { wv ->
                                    (wv.parent as? ViewGroup)?.removeView(wv)
                                    wv.destroy()
                                }
                            } catch (_: Exception) {}
                            webViewInstance = null
                            return true
                        }
                    }

                    loadUrl("file:///android_asset/web/index.html")
                    webViewInstance = this
                }
            },
            update = {
                // Keep web view instance remembered
                webViewInstance = it
            }
        )
    }
}

class AndroidWalletBridge(
    private val viewModel: MainViewModel,
    private val onDownloadCsv: (filename: String, csvContent: String) -> Unit = { _, _ -> }
) {
    @android.webkit.JavascriptInterface
    fun getWalletBalance(): Double {
        val cents = viewModel.wallet.value?.availableBalance ?: 5020000L
        return cents / 100.0
    }

    @android.webkit.JavascriptInterface
    fun getUserId(): String {
        return viewModel.activeUser.value?.id ?: "USR-1001"
    }

    @android.webkit.JavascriptInterface
    fun getUserName(): String {
        return viewModel.activeUser.value?.username ?: "Rahul_Player"
    }

    @android.webkit.JavascriptInterface
    fun syncWalletBalance(balanceRupees: Double, reason: String) {
        viewModel.syncExternalWalletBalance(balanceRupees, reason)
    }

    @android.webkit.JavascriptInterface
    fun submitDeposit(amountRupees: Double, utr: String, method: String) {
        viewModel.submitDepositRequest(amountRupees, utr, method)
    }

    @android.webkit.JavascriptInterface
    fun submitWithdrawal(
        amountRupees: Double,
        upiId: String,
        bankName: String,
        accNo: String,
        ifsc: String,
        bankingName: String
    ) {
        viewModel.submitWithdrawalRequest(amountRupees, upiId, bankName, accNo, ifsc, bankingName)
    }

    @android.webkit.JavascriptInterface
    fun getServerUserId(): String {
        return viewModel.getServerUserId()
    }

    @android.webkit.JavascriptInterface
    fun getBackendBaseUrl(): String {
        return viewModel.backendUrl.value
    }

    @android.webkit.JavascriptInterface
    fun setBackendBaseUrl(url: String) {
        viewModel.setBackendServerUrl(url)
    }

    @android.webkit.JavascriptInterface
    fun getConnectionStatus(): String {
        return viewModel.backendConnectionStatus.value
    }

    @android.webkit.JavascriptInterface
    fun triggerSync() {
        viewModel.triggerManualSync()
    }

    @android.webkit.JavascriptInterface
    fun downloadStatementCsv(filename: String, csvContent: String) {
        onDownloadCsv(filename, csvContent)
    }
}

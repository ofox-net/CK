package com.example.ui.components

import androidx.compose.animation.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.foundation.BorderStroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.example.data.model.MoneyUtils
import com.example.domain.ProvablyFairEngine
import com.example.ui.theme.*

@Composable
fun AppHeader(
    tenantName: String,
    username: String,
    userRole: String,
    walletBalanceCents: Long,
    onDepositClick: () -> Unit,
    onVerifyClick: (() -> Unit)? = null,
    onLogoutClick: (() -> Unit)? = null,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = SurfaceDark,
        tonalElevation = 4.dp
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 14.dp, vertical = 8.dp)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                // Tenant & User info (Left Side - Flexes gracefully without pushing controls)
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    modifier = Modifier.weight(1f, fill = false)
                ) {
                    Box(
                        modifier = Modifier
                            .size(36.dp)
                            .clip(CircleShape)
                            .background(
                                Brush.linearGradient(
                                    listOf(GoldAccent, AmberGlow)
                                )
                            )
                            .then(
                                if (onLogoutClick != null) Modifier.clickable { onLogoutClick() } else Modifier
                            ),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(
                            text = "👑",
                            fontSize = 17.sp
                        )
                    }
                    Spacer(modifier = Modifier.width(8.dp))
                    Column {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                text = tenantName,
                                color = GoldAccent,
                                fontSize = 11.sp,
                                fontWeight = FontWeight.Bold,
                                letterSpacing = 0.5.sp,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                            Spacer(modifier = Modifier.width(4.dp))
                            val displayRole = if (userRole.contains("ADMIN", ignoreCase = true)) "VIP" else userRole
                            Box(
                                modifier = Modifier
                                    .clip(RoundedCornerShape(4.dp))
                                    .background(CardHighlight)
                                    .padding(horizontal = 4.dp, vertical = 1.dp)
                            ) {
                                Text(
                                    text = displayRole,
                                    color = ElectricCyan,
                                    fontSize = 8.sp,
                                    fontWeight = FontWeight.SemiBold
                                )
                            }
                        }
                        Text(
                            text = username,
                            color = TextPrimary,
                            fontSize = 13.sp,
                            fontWeight = FontWeight.Bold,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                    }
                }

                Spacer(modifier = Modifier.width(8.dp))

                // Action: Luxury Single-Line Wallet Balance Pill (Right Side)
                Surface(
                    shape = RoundedCornerShape(18.dp),
                    color = CardHighlight,
                    border = BorderStroke(1.dp, GoldAccent.copy(alpha = 0.55f)),
                    modifier = Modifier
                        .height(36.dp)
                        .clickable { onDepositClick() }
                        .testTag("header_wallet_balance_btn")
                ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.padding(start = 10.dp, end = 6.dp, top = 4.dp, bottom = 4.dp)
                        ) {
                            Icon(
                                imageVector = Icons.Default.AccountBalanceWallet,
                                contentDescription = "Wallet Balance",
                                tint = GoldAccent,
                                modifier = Modifier.size(16.dp)
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text(
                                text = MoneyUtils.formatCents(walletBalanceCents),
                                color = TextPrimary,
                                fontWeight = FontWeight.ExtraBold,
                                fontSize = 13.sp,
                                maxLines = 1,
                                softWrap = false,
                                overflow = TextOverflow.Ellipsis
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Box(
                                modifier = Modifier
                                    .size(22.dp)
                                    .clip(CircleShape)
                                    .background(
                                        Brush.radialGradient(
                                            listOf(NeonGreen, Color(0xFF00C853))
                                        )
                                    ),
                                contentAlignment = Alignment.Center
                            ) {
                                Icon(
                                    imageVector = Icons.Default.Add,
                                    contentDescription = "Quick Deposit",
                                    tint = ObsidianBg,
                                    modifier = Modifier.size(15.dp)
                                )
                            }
                        }
                    }
            }
        }
    }
}

@Composable
fun CasinoChip(
    amountCents: Long,
    isSelected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    val chipColor = when (amountCents) {
        1000L -> ElectricCyan       // ₹10
        5000L -> NeonGreen          // ₹50
        10000L -> GoldAccent        // ₹100
        50000L -> AmberGlow         // ₹500
        100000L -> NeonRed          // ₹1,000
        else -> NeonViolet          // ₹5,000+
    }

    Box(
        modifier = modifier
            .size(54.dp)
            .clip(CircleShape)
            .background(
                Brush.radialGradient(
                    colors = if (isSelected) listOf(chipColor.copy(alpha = 0.9f), chipColor.copy(alpha = 0.5f))
                    else listOf(SurfaceDark, ObsidianBg)
                )
            )
            .border(
                width = if (isSelected) 3.dp else 1.5.dp,
                color = if (isSelected) Color.White else chipColor,
                shape = CircleShape
            )
            .clickable { onClick() }
            .testTag("chip_${amountCents / 100}"),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = "₹${amountCents / 100}",
                color = if (isSelected) Color.White else TextPrimary,
                fontWeight = FontWeight.Bold,
                fontSize = 12.sp,
                textAlign = TextAlign.Center
            )
        }
    }
}

@Composable
fun ProvablyFairDialog(
    serverSeedHash: String,
    currentServerSeed: String?,
    clientSeed: String,
    nonce: Long,
    onDismiss: () -> Unit
) {
    var inputServerSeed by remember { mutableStateOf(currentServerSeed ?: "") }
    var inputClientSeed by remember { mutableStateOf(clientSeed) }
    var inputNonce by remember { mutableStateOf(nonce.toString()) }
    var verificationResult by remember { mutableStateOf<String?>(null) }
    var isVerified by remember { mutableStateOf<Boolean?>(null) }

    Dialog(onDismissRequest = onDismiss) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = SurfaceDark,
            border = borderStroke(1.dp, ElectricCyan.copy(alpha = 0.5f)),
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp)
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            imageVector = Icons.Default.Security,
                            contentDescription = null,
                            tint = ElectricCyan
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "Provably Fair Engine",
                            color = TextPrimary,
                            fontWeight = FontWeight.Bold,
                            fontSize = 18.sp
                        )
                    }
                    IconButton(onClick = onDismiss) {
                        Icon(imageVector = Icons.Default.Close, contentDescription = "Close", tint = TextMuted)
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))
                Text(
                    text = "Every round is cryptographically predetermined using SHA-256 and HMAC. The server seed hash is published BEFORE betting closes.",
                    color = TextSecondary,
                    fontSize = 12.sp
                )

                Spacer(modifier = Modifier.height(14.dp))
                Text(
                    text = "Server Seed Hash (Pre-Committed):",
                    color = GoldAccent,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.SemiBold
                )
                SelectionBox(text = serverSeedHash)

                Spacer(modifier = Modifier.height(10.dp))
                OutlinedTextField(
                    value = inputServerSeed,
                    onValueChange = { inputServerSeed = it },
                    label = { Text("Server Seed (Revealed after round)") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = ElectricCyan,
                        unfocusedBorderColor = CardBorder
                    )
                )

                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = inputClientSeed,
                    onValueChange = { inputClientSeed = it },
                    label = { Text("Client Seed") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = ElectricCyan,
                        unfocusedBorderColor = CardBorder
                    )
                )

                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = inputNonce,
                    onValueChange = { inputNonce = it },
                    label = { Text("Nonce (Round Number)") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = ElectricCyan,
                        unfocusedBorderColor = CardBorder
                    )
                )

                Spacer(modifier = Modifier.height(16.dp))
                Button(
                    onClick = {
                        val nonceVal = inputNonce.toLongOrNull() ?: 0L
                        if (inputServerSeed.isNotBlank()) {
                            val (matches, res) = ProvablyFairEngine.verifyFairness(
                                inputServerSeed,
                                serverSeedHash,
                                inputClientSeed,
                                nonceVal
                            )
                            isVerified = matches
                            verificationResult = "Computed Result: Number ${res.number} (${res.colorString})\nHMAC: ${res.hmacHex.take(16)}..."
                        } else {
                            verificationResult = "Please enter server seed to verify."
                        }
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .testTag("calculate_fairness_btn"),
                    colors = ButtonDefaults.buttonColors(containerColor = ElectricCyan)
                ) {
                    Text("Verify HMAC-SHA256 Result", color = ObsidianBg, fontWeight = FontWeight.Bold)
                }

                if (verificationResult != null) {
                    Spacer(modifier = Modifier.height(12.dp))
                    Surface(
                        color = CardHighlight,
                        shape = RoundedCornerShape(8.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column(modifier = Modifier.padding(10.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(
                                    imageVector = if (isVerified == true) Icons.Default.CheckCircle else Icons.Default.Warning,
                                    contentDescription = null,
                                    tint = if (isVerified == true) NeonGreen else AmberGlow,
                                    modifier = Modifier.size(16.dp)
                                )
                                Spacer(modifier = Modifier.width(6.dp))
                                Text(
                                    text = if (isVerified == true) "Cryptographic Integrity Verified ✓" else "Hash check pending/mismatch",
                                    color = if (isVerified == true) NeonGreen else AmberGlow,
                                    fontWeight = FontWeight.Bold,
                                    fontSize = 12.sp
                                )
                            }
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = verificationResult ?: "",
                                color = TextPrimary,
                                fontSize = 11.sp,
                                fontFamily = FontFamily.Monospace
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun SelectionBox(text: String) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(6.dp))
            .background(CardHighlight)
            .padding(8.dp)
    ) {
        Text(
            text = text,
            color = TextSecondary,
            fontSize = 11.sp,
            fontFamily = FontFamily.Monospace,
            maxLines = 2
        )
    }
}

fun borderStroke(width: androidx.compose.ui.unit.Dp, color: Color) =
    androidx.compose.foundation.BorderStroke(width, color)

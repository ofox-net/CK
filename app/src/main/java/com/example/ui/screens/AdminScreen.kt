package com.example.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.data.model.*
import com.example.ui.MainViewModel
import com.example.ui.components.borderStroke
import com.example.ui.theme.*
import java.text.SimpleDateFormat
import java.util.*

@Composable
fun AdminScreen(
    viewModel: MainViewModel,
    modifier: Modifier = Modifier
) {
    val activeTenantId by viewModel.activeTenantId.collectAsState()
    val activeUserId by viewModel.activeUserId.collectAsState()
    val allTenants by viewModel.allTenants.collectAsState()
    val allUsers by viewModel.allUsers.collectAsState()
    val gameConfig by viewModel.gameConfig.collectAsState()
    val withdrawals by viewModel.allWithdrawals.collectAsState()
    val auditLogs by viewModel.auditLogs.collectAsState()

    var redMultText by remember(gameConfig) { mutableStateOf((gameConfig?.redMultiplier ?: 2.0).toString()) }
    var greenMultText by remember(gameConfig) { mutableStateOf((gameConfig?.greenMultiplier ?: 2.0).toString()) }
    var violetMultText by remember(gameConfig) { mutableStateOf((gameConfig?.violetMultiplier ?: 3.0).toString()) }
    var numberMultText by remember(gameConfig) { mutableStateOf((gameConfig?.numberMultiplier ?: 9.0).toString()) }
    var roundDurationText by remember(gameConfig) { mutableStateOf((gameConfig?.roundDurationSec ?: 180).toString()) }

    LazyColumn(
        modifier = modifier
            .fillMaxSize()
            .background(ObsidianBg)
            .padding(horizontal = 14.dp)
    ) {
        item {
            Spacer(modifier = Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(imageVector = Icons.Default.AdminPanelSettings, contentDescription = null, tint = GoldAccent)
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "Platform Administration",
                    color = TextPrimary,
                    fontSize = 18.sp,
                    fontWeight = FontWeight.Bold
                )
            }
            Text(
                text = "Multi-tenant orchestration, risk controls, withdrawal escrow & audit trail",
                color = TextSecondary,
                fontSize = 12.sp
            )
            Spacer(modifier = Modifier.height(14.dp))

            // 1. Multi-Tenant Switcher
            Text(text = "Active Tenant (Multi-Tenant Isolation)", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 13.sp)
            Spacer(modifier = Modifier.height(6.dp))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                allTenants.forEach { tenant ->
                    val isSelected = tenant.id == activeTenantId
                    Surface(
                        shape = RoundedCornerShape(10.dp),
                        color = if (isSelected) GoldAccent else SurfaceDark,
                        border = borderStroke(1.dp, if (isSelected) GoldAccent else CardBorder),
                        modifier = Modifier.clickable { viewModel.switchTenant(tenant.id) }
                    ) {
                        Text(
                            text = "${tenant.name} (${tenant.code})",
                            color = if (isSelected) ObsidianBg else TextPrimary,
                            fontWeight = FontWeight.Bold,
                            fontSize = 12.sp,
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)
                        )
                    }
                }
            }
            Spacer(modifier = Modifier.height(16.dp))

            // 2. Active User Impersonation Switcher (Test roles and multi-tier payouts live)
            Text(text = "Simulate User / Hierarchy Node", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 13.sp)
            Spacer(modifier = Modifier.height(6.dp))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                allUsers.forEach { user ->
                    val isSelected = user.id == activeUserId
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(8.dp))
                            .background(if (isSelected) ElectricCyan else SurfaceDark)
                            .clickable { viewModel.switchUser(user.id) }
                            .padding(horizontal = 10.dp, vertical = 6.dp)
                    ) {
                        Text(
                            text = "${user.username} [${user.role}]",
                            color = if (isSelected) ObsidianBg else TextSecondary,
                            fontWeight = FontWeight.Bold,
                            fontSize = 11.sp
                        )
                    }
                }
            }
            Spacer(modifier = Modifier.height(18.dp))

            // 3. Game Config & Multipliers
            Surface(
                shape = RoundedCornerShape(16.dp),
                color = SurfaceDark,
                border = borderStroke(1.dp, CardBorder),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Text(
                        text = "Configurable Game Rules & Multipliers",
                        color = TextPrimary,
                        fontSize = 14.sp,
                        fontWeight = FontWeight.Bold
                    )
                    Spacer(modifier = Modifier.height(10.dp))

                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        OutlinedTextField(
                            value = redMultText,
                            onValueChange = { redMultText = it },
                            label = { Text("RED (x)") },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedTextColor = TextPrimary,
                                unfocusedTextColor = TextPrimary,
                                focusedBorderColor = NeonRed,
                                unfocusedBorderColor = CardBorder
                            )
                        )
                        OutlinedTextField(
                            value = greenMultText,
                            onValueChange = { greenMultText = it },
                            label = { Text("GREEN (x)") },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedTextColor = TextPrimary,
                                unfocusedTextColor = TextPrimary,
                                focusedBorderColor = NeonGreen,
                                unfocusedBorderColor = CardBorder
                            )
                        )
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        OutlinedTextField(
                            value = violetMultText,
                            onValueChange = { violetMultText = it },
                            label = { Text("VIOLET (x)") },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedTextColor = TextPrimary,
                                unfocusedTextColor = TextPrimary,
                                focusedBorderColor = NeonViolet,
                                unfocusedBorderColor = CardBorder
                            )
                        )
                        OutlinedTextField(
                            value = numberMultText,
                            onValueChange = { numberMultText = it },
                            label = { Text("Numbers 0-9 (x)") },
                            modifier = Modifier.weight(1f),
                            singleLine = true,
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedTextColor = TextPrimary,
                                unfocusedTextColor = TextPrimary,
                                focusedBorderColor = GoldAccent,
                                unfocusedBorderColor = CardBorder
                            )
                        )
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedTextField(
                        value = roundDurationText,
                        onValueChange = { roundDurationText = it },
                        label = { Text("Round Duration (Seconds)") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedTextColor = TextPrimary,
                            unfocusedTextColor = TextPrimary,
                            focusedBorderColor = ElectricCyan,
                            unfocusedBorderColor = CardBorder
                        )
                    )

                    Spacer(modifier = Modifier.height(12.dp))
                    Button(
                        onClick = {
                            val cfg = gameConfig ?: GameConfigEntity(id = "cfg_$activeTenantId", tenantId = activeTenantId)
                            val updated = cfg.copy(
                                redMultiplier = redMultText.toDoubleOrNull() ?: 2.0,
                                greenMultiplier = greenMultText.toDoubleOrNull() ?: 2.0,
                                violetMultiplier = violetMultText.toDoubleOrNull() ?: 3.0,
                                numberMultiplier = numberMultText.toDoubleOrNull() ?: 9.0,
                                roundDurationSec = roundDurationText.toIntOrNull() ?: 180
                            )
                            viewModel.adminSaveConfig(updated)
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .testTag("save_config_btn"),
                        colors = ButtonDefaults.buttonColors(containerColor = GoldAccent)
                    ) {
                        Text("Save Configuration", color = ObsidianBg, fontWeight = FontWeight.Bold)
                    }
                }
            }
            Spacer(modifier = Modifier.height(18.dp))

            // 4. Withdrawal Escrow Management
            Text(
                text = "Withdrawal Requests Escrow (${withdrawals.size})",
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
                fontSize = 14.sp
            )
            Spacer(modifier = Modifier.height(8.dp))
        }

        if (withdrawals.isEmpty()) {
            item {
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = SurfaceDark,
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Box(modifier = Modifier.padding(16.dp), contentAlignment = Alignment.Center) {
                        Text(text = "No pending withdrawal requests in escrow", color = TextMuted, fontSize = 12.sp)
                    }
                }
                Spacer(modifier = Modifier.height(16.dp))
            }
        } else {
            items(withdrawals) { req ->
                AdminWithdrawalCard(
                    request = req,
                    onApprove = { viewModel.adminApproveWithdrawal(req.id) },
                    onReject = { viewModel.adminRejectWithdrawal(req.id, "Admin review rejected") }
                )
                Spacer(modifier = Modifier.height(8.dp))
            }
            item { Spacer(modifier = Modifier.height(16.dp)) }
        }

        // 5. System Audit Trail
        item {
            Text(
                text = "System Audit Logs (${auditLogs.size})",
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
                fontSize = 14.sp
            )
            Spacer(modifier = Modifier.height(8.dp))
        }

        items(auditLogs) { log ->
            AuditLogItem(log = log)
            Spacer(modifier = Modifier.height(6.dp))
        }

        item { Spacer(modifier = Modifier.height(30.dp)) }
    }
}

@Composable
fun AdminWithdrawalCard(
    request: WithdrawalRequestEntity,
    onApprove: () -> Unit,
    onReject: () -> Unit
) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = SurfaceDark,
        border = borderStroke(1.dp, CardBorder),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        text = "User: ${request.userId}",
                        color = TextPrimary,
                        fontWeight = FontWeight.Bold,
                        fontSize = 13.sp
                    )
                    Text(
                        text = "Destination: ${request.bankOrUpi}",
                        color = TextSecondary,
                        fontSize = 11.sp
                    )
                }

                Text(
                    text = MoneyUtils.formatCents(request.amount),
                    color = GoldAccent,
                    fontWeight = FontWeight.Black,
                    fontSize = 15.sp
                )
            }

            Spacer(modifier = Modifier.height(8.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Box(
                    modifier = Modifier
                        .clip(RoundedCornerShape(4.dp))
                        .background(CardHighlight)
                        .padding(horizontal = 6.dp, vertical = 2.dp)
                ) {
                    Text(text = request.status, color = ElectricCyan, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                }

                if (request.status == "REQUESTED") {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = onApprove,
                            colors = ButtonDefaults.buttonColors(containerColor = NeonGreen),
                            shape = RoundedCornerShape(6.dp),
                            contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
                        ) {
                            Text("Approve Payout", color = ObsidianBg, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        }

                        OutlinedButton(
                            onClick = onReject,
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = NeonRed),
                            border = borderStroke(1.dp, NeonRed),
                            shape = RoundedCornerShape(6.dp),
                            contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp)
                        ) {
                            Text("Reject", color = NeonRed, fontSize = 11.sp)
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun AuditLogItem(log: AuditLogEntity) {
    val dateFormat = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
    val timeStr = dateFormat.format(Date(log.timestamp))

    Surface(
        shape = RoundedCornerShape(8.dp),
        color = CardHighlight,
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(10.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(
                    text = log.action,
                    color = GoldAccent,
                    fontWeight = FontWeight.Bold,
                    fontSize = 11.sp
                )
                Text(
                    text = "$timeStr • ${log.actorUserId}",
                    color = TextMuted,
                    fontSize = 10.sp
                )
            }
            if (log.newValue != null) {
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = log.newValue,
                    color = TextSecondary,
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace
                )
            }
        }
    }
}

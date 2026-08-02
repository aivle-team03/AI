param(
    [string]$InputPath = "output\separated_history_dummy_tables.json",
    [string]$OutputPath = "output\final_history_table_from_separated.json"
)

function Index-By {
    param(
        [array]$Items,
        [string]$Key
    )

    $index = @{}
    foreach ($item in $Items) {
        $index[[string]$item.$Key] = $item
    }
    return $index
}

function Get-Risk {
    param($Category)

    if ($null -eq $Category) {
        return $null
    }
    if ($Category.risk_level) {
        return $Category.risk_level
    }
    return $Category.level
}

function Get-InspectionPart {
    param(
        $InspectionHistory,
        $InspectionById,
        $CategoryById
    )

    if ($null -eq $InspectionHistory) {
        return [ordered]@{
            inspection_history_id = $null
            inspection_id = $null
            inspection_name = $null
            category_id = $null
            category_name = $null
            risk = $null
            inspection_location = $null
            inspection_date = $null
            inspection_user_id = $null
            inspection_user_name = $null
            inspection_content = $null
        }
    }

    $inspection = $InspectionById[[string]$InspectionHistory.inspection_id]
    $categoryId = $InspectionHistory.category_id
    if ($null -eq $categoryId -and $null -ne $inspection) {
        $categoryId = $inspection.category_id
    }
    $category = $CategoryById[[string]$categoryId]
    $inspectionName = $InspectionHistory.name
    if ($null -ne $inspection -and $inspection.name) {
        $inspectionName = $inspection.name
    }
    $categoryName = $InspectionHistory.category_name
    if ($null -ne $category -and $category.category_name) {
        $categoryName = $category.category_name
    }

    return [ordered]@{
        inspection_history_id = $InspectionHistory.inspection_history_id
        inspection_id = $InspectionHistory.inspection_id
        inspection_name = $inspectionName
        category_id = $categoryId
        category_name = $categoryName
        risk = Get-Risk $category
        inspection_location = $InspectionHistory.location
        inspection_date = $InspectionHistory.date
        inspection_user_id = $InspectionHistory.uid
        inspection_user_name = $InspectionHistory.user_name
        inspection_content = $InspectionHistory.content
    }
}

function Add-Properties {
    param(
        [System.Collections.Specialized.OrderedDictionary]$Target,
        [System.Collections.Specialized.OrderedDictionary]$Source
    )

    foreach ($key in $Source.Keys) {
        $Target[$key] = $Source[$key]
    }
}

function Get-ActionPart {
    param($Action)

    if ($null -eq $Action) {
        return [ordered]@{
            action_history_id = $null
            action_name = $null
            action_location = $null
            action_date = $null
            action_user_id = $null
            action_user_name = $null
            action_content = $null
            approval_name = $null
        }
    }

    return [ordered]@{
        action_history_id = $Action.action_history_id
        action_name = $Action.action_name
        action_location = $Action.location
        action_date = $Action.created_at
        action_user_id = $Action.handler_uid
        action_user_name = $Action.handler_name
        action_content = $Action.content
        approval_name = $Action.approver_name
    }
}

$tables = Get-Content -Raw -Encoding UTF8 $InputPath | ConvertFrom-Json
$inspectionActionType = -join @(
    [char]0xC870,
    [char]0xCE58,
    [char]0xC774,
    [char]0xB825
)

$categoryById = Index-By $tables.event_category "category_id"
$inspectionById = Index-By $tables.inspection "inspection_id"
$inspectionHistoryById = Index-By $tables.inspection_history "inspection_history_id"
$eventById = Index-By $tables.event "event_id"
$boardById = Index-By $tables.board "board_id"

$actionInspectionHistoryIds = @{}
foreach ($action in $tables.action_history) {
    if ($null -ne $action.inspection_history_id) {
        $actionInspectionHistoryIds[[string]$action.inspection_history_id] = $true
    }
}

$rows = New-Object System.Collections.Generic.List[object]

foreach ($history in $tables.inspection_history) {
    if ($actionInspectionHistoryIds.ContainsKey([string]$history.inspection_history_id)) {
        continue
    }

    $row = [ordered]@{
        case = "Case 1"
        type = "inspection"
    }
    Add-Properties $row (Get-InspectionPart $history $inspectionById $categoryById)
    $row["before_image_url"] = $null
    Add-Properties $row (Get-ActionPart $null)
    $rows.Add([pscustomobject]$row)
}

foreach ($action in $tables.action_history) {
    if ($null -ne $action.inspection_history_id) {
        $history = $inspectionHistoryById[[string]$action.inspection_history_id]
        $row = [ordered]@{
            case = "Case 2"
            type = $inspectionActionType
        }
        Add-Properties $row (Get-InspectionPart $history $inspectionById $categoryById)
        $row["before_image_url"] = $null
        Add-Properties $row (Get-ActionPart $action)
        $rows.Add([pscustomobject]$row)
        continue
    }

    $category = $categoryById[[string]$action.category_id]
    $event = $eventById[[string]$action.event_id]
    $board = $boardById[[string]$action.board_id]
    $beforeImageUrl = $action.image_url
    $isBoard = $null -ne $action.board_id

    if ($isBoard) {
        if ($null -ne $event -and $event.image_url) {
            $beforeImageUrl = $event.image_url
        }
        elseif ($null -ne $board -and $board.image_url) {
            $beforeImageUrl = $board.image_url
        }
    }
    else {
        if ($null -ne $event -and $event.image_url) {
            $beforeImageUrl = $event.image_url
        }
    }

    $row = [ordered]@{
        case = $(if ($isBoard) { "Case 3" } else { "Case 4" })
        type = $(if ($isBoard) { "board" } else { "event" })
    }
    Add-Properties $row (Get-InspectionPart $null $inspectionById $categoryById)
    $row["category_id"] = $action.category_id
    $row["category_name"] = $(if ($null -ne $category -and $category.category_name) { $category.category_name } else { $action.category_name })
    $row["risk"] = Get-Risk $category
    $row["before_image_url"] = $beforeImageUrl
    $row["board_id"] = $(if ($null -ne $board) { $board.board_id } else { $null })
    $row["event_id"] = $(if ($null -ne $event) { $event.event_id } else { $action.event_id })
    Add-Properties $row (Get-ActionPart $action)
    $rows.Add([pscustomobject]$row)
}

$sortedRows = $rows | Sort-Object case, inspection_date, action_date, action_history_id
$sortedRows | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 $OutputPath

Write-Output "wrote: $OutputPath"
Write-Output "total: $($sortedRows.Count)"
$sortedRows | Group-Object case | Sort-Object Name | ForEach-Object {
    Write-Output "$($_.Name): $($_.Count)"
}
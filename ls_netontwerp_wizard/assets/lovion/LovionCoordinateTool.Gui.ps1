[CmdletBinding()]
param(
    [switch]$SmokeTest,
    [switch]$MacroSmokeTest,
    [string]$StationListPath,
    [string]$StationTestReportPath,
    [string]$StationTestResumePaths,
    [string]$OpenStationResultPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Net.Http
Add-Type -AssemblyName System.Runtime.WindowsRuntime

if (-not ('LovionDataGridView' -as [type])) {
    Add-Type -ReferencedAssemblies 'System.Windows.Forms.dll','System.Drawing.dll','Accessibility.dll' @'
using System;
using System.Collections.Generic;
using System.Windows.Forms;

public class LovionDataGridView : DataGridView
{
    public int AccessibleDisplayedChildCount { get { return AccessibilityObject.GetChildCount(); } }
    protected override AccessibleObject CreateAccessibilityInstance()
    {
        return new DisplayedRowsAccessibleObject(this);
    }

    // Legacy accessibility clients otherwise unshare every off-screen row and
    // instantiate every cell. Keep the standard provider, focus, selection,
    // scrolling and full data model; virtualize only its child enumeration.
    private class DisplayedRowsAccessibleObject : DataGridViewAccessibleObject
    {
        private readonly LovionDataGridView grid;
        public DisplayedRowsAccessibleObject(LovionDataGridView owner) : base(owner) { grid = owner; }

        private List<int> DisplayedChildren()
        {
            var children = new List<int>();
            int fullCount = base.GetChildCount();
            if (fullCount <= 0) return children;
            int headerCount = grid.ColumnHeadersVisible ? 1 : 0;
            if (headerCount > 0) children.Add(0);
            int visibleRank = 0;
            int row = grid.Rows.GetFirstRow(DataGridViewElementStates.Visible);
            while (row >= 0)
            {
                if ((grid.Rows.GetRowState(row) & DataGridViewElementStates.Displayed) != 0)
                    children.Add(headerCount + visibleRank);
                visibleRank++;
                row = grid.Rows.GetNextRow(row, DataGridViewElementStates.Visible);
            }
            // Preserve the standard scrollbar accessibility children too.
            for (int index = headerCount + visibleRank; index < fullCount; index++)
                children.Add(index);
            return children;
        }

        public override int GetChildCount() { return DisplayedChildren().Count; }
        public override AccessibleObject GetChild(int index)
        {
            var children = DisplayedChildren();
            return index >= 0 && index < children.Count ? base.GetChild(children[index]) : null;
        }
    }
}
'@
}

if (-not ('LovionBatchInput' -as [type])) {
    Add-Type -ReferencedAssemblies 'System.Drawing.dll' @'
using System;
using System.Drawing;
using System.Collections.Generic;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Text;

public static class LovionBatchInput
{
    private const uint KEYEVENTF_KEYUP = 0x0002;
    private const uint KEYEVENTF_EXTENDEDKEY = 0x0001;
    private const uint KEYEVENTF_SCANCODE = 0x0008;
    private const uint KEYEVENTF_UNICODE = 0x0004;
    private const uint WM_KEYDOWN = 0x0100;
    private const uint WM_KEYUP = 0x0101;
    private const uint WM_MOUSEMOVE = 0x0200;
    private const uint WM_LBUTTONDOWN = 0x0201;
    private const uint WM_LBUTTONUP = 0x0202;
    private const uint WM_MOUSEWHEEL = 0x020A;
    private const uint MK_LBUTTON = 0x0001;
    private const uint MK_SHIFT = 0x0004;
    private const int WH_MOUSE_LL = 14;
    private const uint WM_QUIT = 0x0012;
    private const uint LLMHF_INJECTED = 0x00000001;
    private const uint LLMHF_LOWER_IL_INJECTED = 0x00000002;
    private delegate bool EnumWindowsCallback(IntPtr window, IntPtr parameter);
    private delegate IntPtr LowLevelMouseCallback(int code, IntPtr wordParameter, IntPtr longParameter);
    private static readonly object MouseGuardSync = new object();
    private static readonly LowLevelMouseCallback MouseGuardCallback = MouseHookCallback;
    private static bool mouseGuardActive;
    private static bool mouseGuardCancelled;
    private static int mouseGuardDepth;
    private static bool mouseGuardHookReady;
    private static bool mouseGuardHookStarted;
    private static bool automationMovePending;
    private static POINT automationMoveTarget;
    private static uint mouseGuardThreadId;
    private static IntPtr mouseGuardHook;
    private static uint lastMouseMoveFlags;
    private static POINT lastMouseMovePosition;
    private static System.Threading.Thread mouseGuardThread;

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT
    {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MSLLHOOKSTRUCT
    {
        public POINT point;
        public uint mouseData;
        public uint flags;
        public uint time;
        public UIntPtr extraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MSG
    {
        public IntPtr window;
        public uint message;
        public UIntPtr wordParameter;
        public IntPtr longParameter;
        public uint time;
        public POINT point;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct INPUT
    {
        public uint type;
        public INPUTUNION data;
    }

    [StructLayout(LayoutKind.Explicit)]
    private struct INPUTUNION
    {
        [FieldOffset(0)] public MOUSEINPUT mouse;
        [FieldOffset(0)] public KEYBDINPUT keyboard;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MOUSEINPUT
    {
        public int dx;
        public int dy;
        public uint mouseData;
        public uint flags;
        public uint time;
        public UIntPtr extraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct KEYBDINPUT
    {
        public ushort virtualKey;
        public ushort scanCode;
        public uint flags;
        public uint time;
        public UIntPtr extraInfo;
    }

    [DllImport("user32.dll")]
    private static extern void keybd_event(byte virtualKey, byte scanCode, uint flags, UIntPtr extraInfo);

    [DllImport("user32.dll")]
    private static extern uint MapVirtualKey(uint code, uint mapType);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern uint SendInput(uint inputCount, INPUT[] inputs, int inputSize);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr window, out RECT rect);

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetConsoleWindow();

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr window, int command);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsCallback callback, IntPtr parameter);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr window, StringBuilder title, int maximumCount);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr window);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr window);

    [DllImport("user32.dll")]
    private static extern bool BringWindowToTop(IntPtr window);

    [DllImport("user32.dll")]
    private static extern bool IsIconic(IntPtr window);

    [DllImport("user32.dll")]
    private static extern bool SetProcessDPIAware();

    [DllImport("user32.dll")]
    private static extern bool GetCursorPos(out POINT point);

    [DllImport("user32.dll")]
    private static extern bool SetCursorPos(int x, int y);

    [DllImport("user32.dll")]
    private static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool PostMessage(IntPtr window, uint message, IntPtr wordParameter, IntPtr longParameter);

    [DllImport("user32.dll")]
    private static extern IntPtr WindowFromPoint(POINT point);

    [DllImport("user32.dll")]
    private static extern bool ScreenToClient(IntPtr window, ref POINT point);

    [DllImport("user32.dll")]
    private static extern bool IsChild(IntPtr parent, IntPtr child);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SetWindowsHookEx(int hookType, LowLevelMouseCallback callback, IntPtr module, uint threadId);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UnhookWindowsHookEx(IntPtr hook);

    [DllImport("user32.dll")]
    private static extern IntPtr CallNextHookEx(IntPtr hook, int code, IntPtr wordParameter, IntPtr longParameter);

    [DllImport("user32.dll")]
    private static extern int GetMessage(out MSG message, IntPtr window, uint minimumFilter, uint maximumFilter);

    [DllImport("user32.dll")]
    private static extern bool TranslateMessage(ref MSG message);

    [DllImport("user32.dll")]
    private static extern IntPtr DispatchMessage(ref MSG message);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool PostThreadMessage(uint threadId, uint message, UIntPtr wordParameter, IntPtr longParameter);

    [DllImport("kernel32.dll")]
    private static extern uint GetCurrentThreadId();

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr GetModuleHandle(string moduleName);

    private static void HandleMouseMovement(uint flags)
    {
        lock (MouseGuardSync)
        {
            if (!mouseGuardActive) return;
            if ((flags & (LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED)) == 0)
            {
                mouseGuardCancelled = true;
            }
        }
    }

    private static IntPtr MouseHookCallback(int code, IntPtr wordParameter, IntPtr longParameter)
    {
        if (code >= 0 && unchecked((uint)wordParameter.ToInt64()) == WM_MOUSEMOVE)
        {
            MSLLHOOKSTRUCT mouseData = (MSLLHOOKSTRUCT)Marshal.PtrToStructure(longParameter, typeof(MSLLHOOKSTRUCT));
            bool isExpectedAutomationMove = false;
            lock (MouseGuardSync)
            {
                lastMouseMoveFlags = mouseData.flags;
                lastMouseMovePosition = mouseData.point;
                if (automationMovePending && mouseData.point.X == automationMoveTarget.X && mouseData.point.Y == automationMoveTarget.Y)
                {
                    automationMovePending = false;
                    isExpectedAutomationMove = true;
                }
            }
            if (!isExpectedAutomationMove) HandleMouseMovement(mouseData.flags);
        }
        return CallNextHookEx(mouseGuardHook, code, wordParameter, longParameter);
    }

    private static void MouseGuardThreadMain()
    {
        uint threadId = GetCurrentThreadId();
        IntPtr hook = SetWindowsHookEx(WH_MOUSE_LL, MouseGuardCallback, GetModuleHandle(null), 0);
        lock (MouseGuardSync)
        {
            mouseGuardThreadId = threadId;
            mouseGuardHook = hook;
            mouseGuardHookStarted = hook != IntPtr.Zero;
            mouseGuardHookReady = true;
            System.Threading.Monitor.PulseAll(MouseGuardSync);
        }
        if (hook == IntPtr.Zero) return;

        MSG message;
        while (GetMessage(out message, IntPtr.Zero, 0, 0) > 0)
        {
            TranslateMessage(ref message);
            DispatchMessage(ref message);
        }
        UnhookWindowsHookEx(hook);
        lock (MouseGuardSync)
        {
            mouseGuardHook = IntPtr.Zero;
            mouseGuardThreadId = 0;
        }
    }

    public static bool StartMouseGuard()
    {
        lock (MouseGuardSync)
        {
            if (mouseGuardActive)
            {
                if (mouseGuardCancelled) return false;
                mouseGuardDepth++;
                return true;
            }

            mouseGuardCancelled = false;
            mouseGuardActive = true;
            mouseGuardDepth = 1;
            mouseGuardHookReady = false;
            mouseGuardHookStarted = false;
            automationMovePending = false;
            lastMouseMoveFlags = 0;
            lastMouseMovePosition = new POINT();
            mouseGuardThread = new System.Threading.Thread(MouseGuardThreadMain);
            mouseGuardThread.IsBackground = true;
            mouseGuardThread.Name = "Lovion mouse movement guard";
            mouseGuardThread.Start();

            DateTime deadline = DateTime.UtcNow.AddSeconds(2);
            while (!mouseGuardHookReady && DateTime.UtcNow < deadline)
            {
                System.Threading.Monitor.Wait(MouseGuardSync, 100);
            }
            if (!mouseGuardHookReady || !mouseGuardHookStarted)
            {
                mouseGuardActive = false;
                mouseGuardDepth = 0;
                return false;
            }
            return true;
        }
    }

    public static void StopMouseGuard()
    {
        System.Threading.Thread threadToJoin = null;
        uint threadId = 0;
        lock (MouseGuardSync)
        {
            if (!mouseGuardActive) return;
            mouseGuardDepth--;
            if (mouseGuardDepth > 0) return;
            mouseGuardDepth = 0;
            mouseGuardActive = false;
            automationMovePending = false;
            threadToJoin = mouseGuardThread;
            mouseGuardThread = null;
            threadId = mouseGuardThreadId;
        }
        if (threadId != 0) PostThreadMessage(threadId, WM_QUIT, UIntPtr.Zero, IntPtr.Zero);
        if (threadToJoin != null && threadToJoin != System.Threading.Thread.CurrentThread)
        {
            threadToJoin.Join(200);
        }
    }

    public static bool IsMouseGuardCancelled()
    {
        lock (MouseGuardSync)
        {
            return mouseGuardActive && mouseGuardCancelled;
        }
    }

    public static string GetMouseGuardDebugInfo()
    {
        lock (MouseGuardSync)
        {
            return String.Format("active={0}; cancelled={1}; flags={2}; x={3}; y={4}",
                mouseGuardActive, mouseGuardCancelled, lastMouseMoveFlags, lastMouseMovePosition.X, lastMouseMovePosition.Y);
        }
    }

    private static bool SetAutomationCursorPos(int x, int y)
    {
        lock (MouseGuardSync)
        {
            if (mouseGuardActive && mouseGuardCancelled) return false;
            if (mouseGuardActive)
            {
                automationMoveTarget.X = x;
                automationMoveTarget.Y = y;
                automationMovePending = true;
            }
        }
        bool moved = SetCursorPos(x, y);
        if (!moved)
        {
            lock (MouseGuardSync) { automationMovePending = false; }
        }
        return moved;
    }

    private static IntPtr FindLovionWindow()
    {
        IntPtr target = IntPtr.Zero;
        EnumWindows(delegate(IntPtr window, IntPtr parameter)
        {
            if (!IsWindowVisible(window)) return true;
            StringBuilder title = new StringBuilder(1024);
            GetWindowText(window, title, title.Capacity);
            if (title.ToString().IndexOf("Lovion BIS", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                target = window;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return target;
    }

    public static IntPtr GetLovionWindow()
    {
        return FindLovionWindow();
    }

    public static bool IsLovionWindowReady()
    {
        IntPtr target = FindLovionWindow();
        RECT rect;
        return target != IntPtr.Zero && !IsIconic(target) && GetWindowRect(target, out rect) &&
            (rect.Right - rect.Left) >= 1000 && (rect.Bottom - rect.Top) >= 500;
    }

    private static IntPtr PointToParameter(POINT point)
    {
        int packed = unchecked((point.Y << 16) | (point.X & 0xFFFF));
        return new IntPtr(packed);
    }

    private static bool TryGetBackgroundTarget(int offsetX, int offsetY, out IntPtr messageTarget, out POINT clientPoint, out POINT screenPoint)
    {
        messageTarget = IntPtr.Zero;
        clientPoint = new POINT();
        screenPoint = new POINT();

        IntPtr lovionWindow = FindLovionWindow();
        RECT rect;
        if (lovionWindow == IntPtr.Zero || IsIconic(lovionWindow) || !GetWindowRect(lovionWindow, out rect)) return false;

        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500 || offsetX < 0 || offsetY < 0 || offsetX >= width || offsetY >= height) return false;

        screenPoint.X = rect.Left + offsetX;
        screenPoint.Y = rect.Top + offsetY;
        IntPtr pointWindow = WindowFromPoint(screenPoint);
        if (pointWindow == IntPtr.Zero || (pointWindow != lovionWindow && !IsChild(lovionWindow, pointWindow))) return false;

        clientPoint = screenPoint;
        if (!ScreenToClient(pointWindow, ref clientPoint)) return false;
        messageTarget = pointWindow;
        return true;
    }

    private static bool PostBackgroundClick(int offsetX, int offsetY, bool shift)
    {
        IntPtr messageTarget;
        POINT clientPoint;
        POINT screenPoint;
        if (!TryGetBackgroundTarget(offsetX, offsetY, out messageTarget, out clientPoint, out screenPoint)) return false;

        uint modifiers = shift ? MK_SHIFT : 0;
        try
        {
            if (shift) PostMessage(messageTarget, WM_KEYDOWN, new IntPtr(0x10), new IntPtr(1));
            PostMessage(messageTarget, WM_MOUSEMOVE, new IntPtr((int)modifiers), PointToParameter(clientPoint));
            if (!PostMessage(messageTarget, WM_LBUTTONDOWN, new IntPtr((int)(modifiers | MK_LBUTTON)), PointToParameter(clientPoint))) return false;
            System.Threading.Thread.Sleep(40);
            bool released = PostMessage(messageTarget, WM_LBUTTONUP, new IntPtr((int)modifiers), PointToParameter(clientPoint));
            System.Threading.Thread.Sleep(150);
            return released;
        }
        finally
        {
            if (shift) PostMessage(messageTarget, WM_KEYUP, new IntPtr(0x10), new IntPtr(unchecked((int)0xC0000001)));
        }
    }

    public static bool BackgroundTapLovionKey(int virtualKey)
    {
        IntPtr messageTarget;
        POINT clientPoint;
        POINT screenPoint;
        if (!TryGetBackgroundTarget(800, 400, out messageTarget, out clientPoint, out screenPoint)) return false;
        if (!PostMessage(messageTarget, WM_KEYDOWN, new IntPtr(virtualKey), new IntPtr(1))) return false;
        System.Threading.Thread.Sleep(30);
        return PostMessage(messageTarget, WM_KEYUP, new IntPtr(virtualKey), new IntPtr(unchecked((int)0xC0000001)));
    }

    public static bool FocusLovionGridFirstRowBackground()
    {
        return ClickLovionGridRowBackground(0);
    }

    public static bool ScrollLovionGridBackground(int wheelSteps)
    {
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;
        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500) return false;

        int offsetX = Math.Min(width - 300, Math.Max(650, (int)(width * 0.42)));
        int offsetY = Math.Min(height - 120, 400);
        IntPtr messageTarget;
        POINT clientPoint;
        POINT screenPoint;
        if (!TryGetBackgroundTarget(offsetX, offsetY, out messageTarget, out clientPoint, out screenPoint)) return false;

        int direction = wheelSteps >= 0 ? -120 : 120;
        int count = Math.Abs(wheelSteps);
        PostMessage(messageTarget, WM_MOUSEMOVE, IntPtr.Zero, PointToParameter(clientPoint));
        for (int index = 0; index < count; index++)
        {
            IntPtr wheelParameter = new IntPtr(unchecked(direction << 16));
            if (!PostMessage(messageTarget, WM_MOUSEWHEEL, wheelParameter, PointToParameter(screenPoint))) return false;
            System.Threading.Thread.Sleep(45);
        }
        System.Threading.Thread.Sleep(250);
        return true;
    }

    public static bool ShiftClickLovionGridRowBackground(int visibleRowIndex)
    {
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;
        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500) return false;
        int rowIndex = Math.Max(0, Math.Min(13, visibleRowIndex));
        int offsetX = Math.Min(width - 300, Math.Max(650, (int)(width * 0.42)));
        int offsetY = Math.Min(height - 100, 255 + (rowIndex * 22));
        return PostBackgroundClick(offsetX, offsetY, true);
    }

    public static bool ClickLovionGridRowBackground(int visibleRowIndex)
    {
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;
        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500) return false;
        int rowIndex = Math.Max(0, Math.Min(13, visibleRowIndex));
        int offsetX = Math.Min(width - 300, Math.Max(650, (int)(width * 0.42)));
        int offsetY = Math.Min(height - 100, 255 + (rowIndex * 22));
        return PostBackgroundClick(offsetX, offsetY, false);
    }

    public static bool ExportLovionSelectionToClipboardBackground()
    {
        if (!PostBackgroundClick(210, 47, false)) return false;
        System.Threading.Thread.Sleep(750);
        if (!PostBackgroundClick(528, 95, false)) return false;
        System.Threading.Thread.Sleep(120);
        return true;
    }

    public static void KeyDown(int virtualKey)
    {
        SendKeyboardInput(virtualKey, false);
    }

    public static void KeyUp(int virtualKey)
    {
        SendKeyboardInput(virtualKey, true);
    }

    private static void SendKeyboardInput(int virtualKey, bool keyUp)
    {
        INPUT input = new INPUT();
        input.type = 1;
        input.data.keyboard.virtualKey = (ushort)virtualKey;
        input.data.keyboard.scanCode = 0;
        input.data.keyboard.flags = keyUp ? KEYEVENTF_KEYUP : 0;
        input.data.keyboard.time = 0;
        input.data.keyboard.extraInfo = UIntPtr.Zero;
        if (SendInput(1, new INPUT[] { input }, Marshal.SizeOf(typeof(INPUT))) != 1)
        {
            keybd_event((byte)virtualKey, 0, keyUp ? KEYEVENTF_KEYUP : 0, UIntPtr.Zero);
        }
    }

    public static void ReleaseModifiers()
    {
        KeyUp(0x10); // Shift
        KeyUp(0xA0); // Left Shift
        KeyUp(0xA1); // Right Shift
        KeyUp(0x11); // Control
        KeyUp(0xA2); // Left Control
        KeyUp(0xA3); // Right Control
    }

    public static void Tap(int virtualKey)
    {
        KeyDown(virtualKey);
        KeyUp(virtualKey);
    }

    // Citrix sometimes ignores virtual-key-only SendInput events for a held
    // modifier followed by an arrow.  The physical keyboard path below sends
    // scan codes, which matches the input generated by a real keyboard.
    public static void PhysicalKeyDown(int virtualKey)
    {
        SendPhysicalKeyboardInput(virtualKey, false);
    }

    public static void PhysicalKeyUp(int virtualKey)
    {
        SendPhysicalKeyboardInput(virtualKey, true);
    }

    public static void PhysicalTap(int virtualKey)
    {
        PhysicalKeyDown(virtualKey);
        System.Threading.Thread.Sleep(25);
        PhysicalKeyUp(virtualKey);
    }

    private static void SendPhysicalKeyboardInput(int virtualKey, bool keyUp)
    {
        ushort scanCode = (ushort)MapVirtualKey((uint)virtualKey, 0);
        if (scanCode == 0)
        {
            SendKeyboardInput(virtualKey, keyUp);
            return;
        }

        uint flags = KEYEVENTF_SCANCODE;
        if (virtualKey == 0x26 || virtualKey == 0x28 || virtualKey == 0x25 || virtualKey == 0x27 || virtualKey == 0x21 || virtualKey == 0x22 || virtualKey == 0x2D || virtualKey == 0x2E || virtualKey == 0x24 || virtualKey == 0x23)
        {
            flags |= KEYEVENTF_EXTENDEDKEY;
        }
        if (keyUp) flags |= KEYEVENTF_KEYUP;

        INPUT input = new INPUT();
        input.type = 1;
        input.data.keyboard.virtualKey = 0;
        input.data.keyboard.scanCode = scanCode;
        input.data.keyboard.flags = flags;
        input.data.keyboard.time = 0;
        input.data.keyboard.extraInfo = UIntPtr.Zero;
        if (SendInput(1, new INPUT[] { input }, Marshal.SizeOf(typeof(INPUT))) != 1)
        {
            keybd_event((byte)virtualKey, (byte)scanCode, flags & ~KEYEVENTF_SCANCODE, UIntPtr.Zero);
        }
    }

    public static void HideConsoleWindow()
    {
        IntPtr consoleWindow = GetConsoleWindow();
        if (consoleWindow != IntPtr.Zero)
        {
            ShowWindow(consoleWindow, 0);
        }
    }

    public static void EnableDpiAwareness()
    {
        try { SetProcessDPIAware(); } catch { }
    }

    public static bool ActivateLovionWindow()
    {
        IntPtr target = FindLovionWindow();

        if (target == IntPtr.Zero) return false;
        if (IsIconic(target))
        {
            ShowWindow(target, 9);
        }
        // Release Windows' foreground lock before switching from the Workbench to Citrix.
        keybd_event(0x12, 0, 0, UIntPtr.Zero);
        keybd_event(0x12, 0, 0x0002, UIntPtr.Zero);
        BringWindowToTop(target);
        return SetForegroundWindow(target);
    }

    public static bool ClickLovionRecordedPoint(int recordedX, int recordedY, int clickCount)
    {
        const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
        const uint MOUSEEVENTF_LEFTUP = 0x0004;
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;

        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500) return false;

        double scaleX = width >= 1800 ? 1.0 : width / 1920.0;
        double scaleY = height >= 900 ? 1.0 : height / 1080.0;
        int x = rect.Left + Math.Max(2, Math.Min(width - 3, (int)Math.Round(recordedX * scaleX)));
        int y = rect.Top + Math.Max(2, Math.Min(height - 3, (int)Math.Round(recordedY * scaleY)));
        if (!SetAutomationCursorPos(x, y)) return false;
        System.Threading.Thread.Sleep(70);
        if (IsMouseGuardCancelled()) return false;
        int boundedClickCount = Math.Max(1, Math.Min(2, clickCount));
        for (int index = 0; index < boundedClickCount; index++)
        {
            if (IsMouseGuardCancelled()) return false;
            mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
            System.Threading.Thread.Sleep(35);
            mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
            if (index + 1 < boundedClickCount) System.Threading.Thread.Sleep(90);
        }
        System.Threading.Thread.Sleep(80);
        return !IsMouseGuardCancelled();
    }

    public static bool ClickLovionWindowPoint(int offsetX, int offsetY, int clickCount)
    {
        const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
        const uint MOUSEEVENTF_LEFTUP = 0x0004;
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;

        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500 || offsetX < 0 || offsetY < 0 || offsetX >= width || offsetY >= height) return false;
        int x = rect.Left + Math.Max(2, Math.Min(width - 3, offsetX));
        int y = rect.Top + Math.Max(2, Math.Min(height - 3, offsetY));
        if (!SetAutomationCursorPos(x, y)) return false;
        System.Threading.Thread.Sleep(70);
        if (IsMouseGuardCancelled()) return false;
        int boundedClickCount = Math.Max(1, Math.Min(2, clickCount));
        for (int index = 0; index < boundedClickCount; index++)
        {
            if (IsMouseGuardCancelled()) return false;
            mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
            System.Threading.Thread.Sleep(35);
            mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
            if (index + 1 < boundedClickCount) System.Threading.Thread.Sleep(90);
        }
        System.Threading.Thread.Sleep(80);
        return !IsMouseGuardCancelled();
    }

    public static bool DragLovionWindowPoints(int startX, int startY, int endX, int endY)
    {
        const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
        const uint MOUSEEVENTF_LEFTUP = 0x0004;
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;

        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500 || startX < 0 || startY < 0 || endX < 0 || endY < 0 || startX >= width || endX >= width || startY >= height || endY >= height) return false;
        if (!SetAutomationCursorPos(rect.Left + startX, rect.Top + startY)) return false;
        System.Threading.Thread.Sleep(80);
        if (IsMouseGuardCancelled()) return false;

        bool buttonDown = false;
        try
        {
            mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
            buttonDown = true;
            int distance = Math.Max(Math.Abs(endX - startX), Math.Abs(endY - startY));
            int steps = Math.Max(8, Math.Min(40, distance / 10));
            for (int index = 1; index <= steps; index++)
            {
                if (IsMouseGuardCancelled()) return false;
                int x = startX + (int)Math.Round((endX - startX) * (index / (double)steps));
                int y = startY + (int)Math.Round((endY - startY) * (index / (double)steps));
                if (!SetAutomationCursorPos(rect.Left + x, rect.Top + y)) return false;
                System.Threading.Thread.Sleep(25);
            }
            mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
            buttonDown = false;
            System.Threading.Thread.Sleep(120);
            return !IsMouseGuardCancelled();
        }
        finally
        {
            if (buttonDown) mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
        }
    }

    public static int[] FindLovionYellowMarkerPoints()
    {
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return new int[0];

        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500) return new int[0];

        using (Bitmap bitmap = new Bitmap(width, height))
        {
            using (Graphics graphics = Graphics.FromImage(bitmap))
            {
                graphics.CopyFromScreen(rect.Left, rect.Top, 0, 0, new System.Drawing.Size(width, height));
            }

            BitmapData bitmapData = bitmap.LockBits(
                new Rectangle(0, 0, width, height),
                ImageLockMode.ReadOnly,
                PixelFormat.Format32bppArgb);
            try
            {
                int stride = bitmapData.Stride;
                int absoluteStride = Math.Abs(stride);
                byte[] pixels = new byte[absoluteStride * height];
                Marshal.Copy(bitmapData.Scan0, pixels, 0, pixels.Length);

                bool[,] visited = new bool[width, height];
                List<POINT> candidates = new List<POINT>();
                for (int y = 145; y < height - 5; y += 2)
                {
                    for (int x = 45; x < width - 5; x += 2)
                    {
                        if (visited[x, y] || !IsYellowMarkerPixel(pixels, stride, height, x, y)) continue;

                        Queue<POINT> queue = new Queue<POINT>();
                        queue.Enqueue(new POINT { X = x, Y = y });
                        visited[x, y] = true;
                        int minX = x, maxX = x, minY = y, maxY = y, pixelCount = 0;
                        while (queue.Count > 0)
                        {
                            POINT point = queue.Dequeue();
                            pixelCount++;
                            minX = Math.Min(minX, point.X);
                            maxX = Math.Max(maxX, point.X);
                            minY = Math.Min(minY, point.Y);
                            maxY = Math.Max(maxY, point.Y);
                            for (int deltaY = -1; deltaY <= 1; deltaY++)
                            {
                                for (int deltaX = -1; deltaX <= 1; deltaX++)
                                {
                                    if (deltaX == 0 && deltaY == 0) continue;
                                    int nextX = point.X + deltaX;
                                    int nextY = point.Y + deltaY;
                                    if (nextX < 45 || nextX >= width - 5 || nextY < 145 || nextY >= height - 5 || visited[nextX, nextY]) continue;
                                    if (!IsYellowMarkerPixel(pixels, stride, height, nextX, nextY)) continue;
                                    visited[nextX, nextY] = true;
                                    queue.Enqueue(new POINT { X = nextX, Y = nextY });
                                }
                            }
                        }

                        int componentWidth = maxX - minX + 1;
                        int componentHeight = maxY - minY + 1;
                        if (pixelCount >= 8 && pixelCount <= 1200 && componentWidth <= 70 && componentHeight <= 70)
                        {
                            candidates.Add(new POINT { X = (minX + maxX) / 2, Y = (minY + maxY) / 2 });
                        }
                    }
                }

                int centerX = width / 2;
                int centerY = (145 + height) / 2;
                candidates.Sort(delegate(POINT left, POINT right)
                {
                    long leftDistance = ((long)left.X - centerX) * ((long)left.X - centerX) + ((long)left.Y - centerY) * ((long)left.Y - centerY);
                    long rightDistance = ((long)right.X - centerX) * ((long)right.X - centerX) + ((long)right.Y - centerY) * ((long)right.Y - centerY);
                    return leftDistance.CompareTo(rightDistance);
                });

                int count = Math.Min(candidates.Count, 12);
                int[] result = new int[count * 2];
                for (int index = 0; index < count; index++)
                {
                    result[index * 2] = candidates[index].X;
                    result[(index * 2) + 1] = candidates[index].Y;
                }
                return result;
            }
            finally
            {
                bitmap.UnlockBits(bitmapData);
            }
        }
    }

    private static bool IsYellowMarkerPixel(byte[] pixels, int stride, int height, int x, int y)
    {
        int absoluteStride = Math.Abs(stride);
        int row = stride >= 0 ? y : height - 1 - y;
        int offset = (row * absoluteStride) + (x * 4);
        byte blue = pixels[offset];
        byte green = pixels[offset + 1];
        byte red = pixels[offset + 2];
        return red >= 220 && green >= 125 && green <= 240 && blue <= 120 && red >= blue + 100;
    }

    public static void Chord(int modifierKey, int virtualKey)
    {
        if (IsMouseGuardCancelled()) return;
        ReleaseModifiers();
        KeyDown(modifierKey);
        System.Threading.Thread.Sleep(35);
        if (IsMouseGuardCancelled())
        {
            KeyUp(modifierKey);
            return;
        }
        Tap(virtualKey);
        System.Threading.Thread.Sleep(35);
        KeyUp(modifierKey);
    }

    public static bool TypeUnicodeText(string text)
    {
        if (String.IsNullOrEmpty(text)) return true;
        ReleaseModifiers();
        foreach (char character in text)
        {
            if (IsMouseGuardCancelled()) return false;
            INPUT down = new INPUT();
            down.type = 1;
            down.data.keyboard.virtualKey = 0;
            down.data.keyboard.scanCode = character;
            down.data.keyboard.flags = KEYEVENTF_UNICODE;

            INPUT up = down;
            up.data.keyboard.flags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP;
            if (SendInput(2, new INPUT[] { down, up }, Marshal.SizeOf(typeof(INPUT))) != 2) return false;
            System.Threading.Thread.Sleep(12);
        }
        return true;
    }

    public static bool FocusLovionGridFirstRow()
    {
        const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
        const uint MOUSEEVENTF_LEFTUP = 0x0004;
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;

        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500) return false;

        // The Woonplaats cell is plain table content; unlike linked columns it does not open an editor.
        int x = rect.Left + Math.Min(width - 300, Math.Max(650, (int)(width * 0.42)));
        int y = rect.Top + Math.Min(height - 100, 255);
        if (!SetAutomationCursorPos(x, y)) return false;
        System.Threading.Thread.Sleep(80);
        if (IsMouseGuardCancelled()) return false;
        mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
        mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
        System.Threading.Thread.Sleep(120);
        return !IsMouseGuardCancelled();
    }

    public static bool ScrollLovionGrid(int wheelSteps)
    {
        const uint MOUSEEVENTF_WHEEL = 0x0800;
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;

        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500) return false;

        int x = rect.Left + Math.Min(width - 300, Math.Max(650, (int)(width * 0.42)));
        int y = rect.Top + Math.Min(height - 120, 400);
        int direction = wheelSteps >= 0 ? -120 : 120;
        int count = Math.Abs(wheelSteps);
        if (!SetAutomationCursorPos(x, y)) return false;
        System.Threading.Thread.Sleep(80);
        for (int index = 0; index < count; index++)
        {
            if (IsMouseGuardCancelled()) return false;
            mouse_event(MOUSEEVENTF_WHEEL, 0, 0, unchecked((uint)direction), UIntPtr.Zero);
            System.Threading.Thread.Sleep(45);
        }
        System.Threading.Thread.Sleep(250);
        return !IsMouseGuardCancelled();
    }

    public static bool ShiftClickLovionGridRow(int visibleRowIndex)
    {
        const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
        const uint MOUSEEVENTF_LEFTUP = 0x0004;
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;

        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500) return false;

        int rowIndex = Math.Max(0, Math.Min(13, visibleRowIndex));
        int x = rect.Left + Math.Min(width - 300, Math.Max(650, (int)(width * 0.42)));
        int y = rect.Top + Math.Min(height - 100, 255 + (rowIndex * 22));
        try
        {
            if (!SetAutomationCursorPos(x, y)) return false;
            System.Threading.Thread.Sleep(80);
            if (IsMouseGuardCancelled()) return false;
            KeyDown(0x10);
            System.Threading.Thread.Sleep(120);
            if (IsMouseGuardCancelled()) return false;
            mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
            System.Threading.Thread.Sleep(40);
            mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
            System.Threading.Thread.Sleep(120);
            return !IsMouseGuardCancelled();
        }
        finally
        {
            ReleaseModifiers();
        }
    }

    public static bool ClickLovionGridRow(int visibleRowIndex)
    {
        const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
        const uint MOUSEEVENTF_LEFTUP = 0x0004;
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;

        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500) return false;

        int rowIndex = Math.Max(0, Math.Min(13, visibleRowIndex));
        int x = rect.Left + Math.Min(width - 300, Math.Max(650, (int)(width * 0.42)));
        int y = rect.Top + Math.Min(height - 100, 255 + (rowIndex * 22));
        if (!SetAutomationCursorPos(x, y)) return false;
        System.Threading.Thread.Sleep(80);
        if (IsMouseGuardCancelled()) return false;
        mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
        System.Threading.Thread.Sleep(40);
        mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
        System.Threading.Thread.Sleep(150);
        return !IsMouseGuardCancelled();
    }

    public static bool ExportLovionSelectionToClipboard()
    {
        const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
        const uint MOUSEEVENTF_LEFTUP = 0x0004;
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;

        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500) return false;

        try
        {
            ReleaseModifiers();

            // Open the Exporteren ribbon tab.
            if (!SetAutomationCursorPos(rect.Left + 210, rect.Top + 47)) return false;
            System.Threading.Thread.Sleep(100);
            if (IsMouseGuardCancelled()) return false;
            mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
            mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
            System.Threading.Thread.Sleep(750);

            // Use the direct Kopieer naar klembord button in the export ribbon.
            if (!SetAutomationCursorPos(rect.Left + 528, rect.Top + 95)) return false;
            System.Threading.Thread.Sleep(100);
            if (IsMouseGuardCancelled()) return false;
            mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
            mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
            System.Threading.Thread.Sleep(120);
            return !IsMouseGuardCancelled();
        }
        finally
        {
            ReleaseModifiers();
        }
    }

    private static bool FastClickLovionOffset(int offsetX, int offsetY, bool shift)
    {
        const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
        const uint MOUSEEVENTF_LEFTUP = 0x0004;
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;
        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500 || offsetX < 0 || offsetY < 0 || offsetX >= width || offsetY >= height) return false;

        try
        {
            if (!SetAutomationCursorPos(rect.Left + offsetX, rect.Top + offsetY)) return false;
            System.Threading.Thread.Sleep(25);
            if (IsMouseGuardCancelled()) return false;
            if (shift) KeyDown(0x10);
            mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
            mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
            return true;
        }
        finally
        {
            if (shift) KeyUp(0x10);
        }
    }

    public static bool FocusLovionGridFirstRowFast()
    {
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;
        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500) return false;
        int offsetX = Math.Min(width - 300, Math.Max(650, (int)(width * 0.42)));
        int offsetY = Math.Min(height - 100, 255);
        bool result = FastClickLovionOffset(offsetX, offsetY, false);
        System.Threading.Thread.Sleep(120);
        return result;
    }

    public static bool ScrollLovionGridFast(int wheelSteps)
    {
        const uint MOUSEEVENTF_WHEEL = 0x0800;
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;
        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500) return false;
        int x = rect.Left + Math.Min(width - 300, Math.Max(650, (int)(width * 0.42)));
        int y = rect.Top + Math.Min(height - 120, 400);
        int direction = wheelSteps >= 0 ? -120 : 120;
        int count = Math.Abs(wheelSteps);

        if (!SetAutomationCursorPos(x, y)) return false;
        System.Threading.Thread.Sleep(25);
        for (int index = 0; index < count; index++)
        {
            if (IsMouseGuardCancelled()) return false;
            mouse_event(MOUSEEVENTF_WHEEL, 0, 0, unchecked((uint)direction), UIntPtr.Zero);
            System.Threading.Thread.Sleep(8);
        }
        System.Threading.Thread.Sleep(250);
        return !IsMouseGuardCancelled();
    }

    public static bool ShiftClickLovionGridRowFast(int visibleRowIndex)
    {
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;
        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500) return false;
        int rowIndex = Math.Max(0, Math.Min(13, visibleRowIndex));
        int offsetX = Math.Min(width - 300, Math.Max(650, (int)(width * 0.42)));
        int offsetY = Math.Min(height - 100, 255 + (rowIndex * 22));
        bool result = FastClickLovionOffset(offsetX, offsetY, true);
        System.Threading.Thread.Sleep(150);
        return result;
    }

    public static bool ClickLovionGridRowFast(int visibleRowIndex)
    {
        IntPtr target = FindLovionWindow();
        RECT rect;
        if (target == IntPtr.Zero || !GetWindowRect(target, out rect)) return false;
        int width = rect.Right - rect.Left;
        int height = rect.Bottom - rect.Top;
        if (width < 1000 || height < 500) return false;
        int rowIndex = Math.Max(0, Math.Min(13, visibleRowIndex));
        int offsetX = Math.Min(width - 300, Math.Max(650, (int)(width * 0.42)));
        int offsetY = Math.Min(height - 100, 255 + (rowIndex * 22));
        bool result = FastClickLovionOffset(offsetX, offsetY, false);
        System.Threading.Thread.Sleep(150);
        return result;
    }

    public static bool ExportLovionSelectionToClipboardFast()
    {
        ReleaseModifiers();
        if (!FastClickLovionOffset(210, 47, false)) return false;
        System.Threading.Thread.Sleep(750);
        if (!FastClickLovionOffset(528, 95, false)) return false;
        System.Threading.Thread.Sleep(120);
        return true;
    }

    public static bool IsLovionForegroundWindow()
    {
        IntPtr window = GetForegroundWindow();
        if (window == IntPtr.Zero) return false;
        StringBuilder title = new StringBuilder(1024);
        GetWindowText(window, title, title.Capacity);
        return title.ToString().IndexOf("Lovion BIS", StringComparison.OrdinalIgnoreCase) >= 0;
    }
}
'@
}

$script:AppName = 'Lovion Coordinate Tool'
$script:AppVersion = '1.4.0'
$script:ScriptDirectory = if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) { (Get-Location).Path } else { $PSScriptRoot }
$script:EmbeddedLovionMacroXmlBase64 = $null
$script:LovionMacroRelativePath = Join-Path -Path 'assets' -ChildPath 'Trafo zoeken macro rapport.xml'
$script:CurrentDirectory = (Get-Location).Path
$script:Table = New-Object System.Data.DataTable 'Connections'
$script:Grid = $null
$script:StatusLabel = $null
$script:MainForm = $null
$script:DefaultGeocodeDelayMs = 0
$script:DefaultGeocodeConcurrency = 6
$script:EnexisWfsUrl = 'https://opendata.enexis.nl/geoserver/wfs'
$script:EnexisServiceConnectionLayer = 'Enexis_Opendata:asm_e_lv_service_connection'
$script:EnexisStreetFurnitureLayer = 'Enexis_Opendata:asm_e_lv_street_furniture'
$script:WfsSnapDistanceMeters = 25
$script:WfsStreetFurnitureSnapDistanceMeters = 100
$script:WfsBufferMeters = 100
$script:StreetFurnitureTermsConfigPath = Join-Path -Path $script:ScriptDirectory -ChildPath 'street_furniture_terms.json'
$script:LovionBatchLogPath = Join-Path -Path $script:ScriptDirectory -ChildPath 'LovionBatch.log'
$script:StationTestReportPath = $StationTestReportPath
$script:StationTestRecords = New-Object System.Collections.Generic.List[object]
$script:StationTestRequested = @()
$script:WinRtAsTaskMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq 'AsTask' -and
        $_.IsGenericMethod -and
        $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } |
    Select-Object -First 1
$script:BitmapDecoderType = [type]::GetType('Windows.Graphics.Imaging.BitmapDecoder, Windows, ContentType=WindowsRuntime')
$script:SoftwareBitmapType = [type]::GetType('Windows.Graphics.Imaging.SoftwareBitmap, Windows, ContentType=WindowsRuntime')
$script:OcrResultType = [type]::GetType('Windows.Media.Ocr.OcrResult, Windows, ContentType=WindowsRuntime')
$script:OcrEngineType = [type]::GetType('Windows.Media.Ocr.OcrEngine, Windows, ContentType=WindowsRuntime')
$script:LovionOcrEngine = $null
$script:OcrSnapshotCount = 0
$script:DefaultStreetFurnitureTerms = @(
    'riool',
    'fontein',
    'putkast',
    'ovkast',
    'vrikast',
    'parkeer',
    'slagboom',
    'verkeer',
    'brug',
    'sluis',
    'abri',
    'bushalte',
    'reclame',
    'cai',
    'telecom',
    'telefoon',
    'sirene',
    'camera',
    'flits',
    'bord',
    'verlichting',
    'mast',
    'lantaarn',
    'marktkast',
    'kermis',
    'feest',
    'afval',
    'vuil',
    'container',
    'toilet',
    'urinoir'
)
$script:StreetFurnitureTerms = @()

function Normalize-Text {
    param($Value)

    if ($null -eq $Value) {
        return ''
    }

    $text = [string]$Value
    $text = $text.Trim().ToUpperInvariant()
    $text = $text -replace '\s+', ' '
    return $text
}

function Normalize-Postcode {
    param($Value)

    if ($null -eq $Value) {
        return ''
    }

    return ([string]$Value).ToUpperInvariant() -replace '\s+', ''
}

function Normalize-HouseNumber {
    param($Value)

    if ($null -eq $Value) {
        return ''
    }

    return ([string]$Value).ToUpperInvariant() -replace '\s+', ''
}

function Get-HouseNumberDigits {
    param($Value)

    $normalized = Normalize-HouseNumber $Value
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return ''
    }

    $match = [regex]::Match($normalized, '^\d+')
    if (-not $match.Success) {
        return $normalized
    }

    return $match.Value
}

function Join-NonEmpty {
    param([string[]]$Parts)

    $filtered = @()
    foreach ($part in $Parts) {
        if (-not [string]::IsNullOrWhiteSpace($part)) {
            $filtered += $part.Trim()
        }
    }

    return ($filtered -join ' ').Trim()
}

function Normalize-ComparableText {
    param($Value)

    $text = Normalize-Text $Value
    if ([string]::IsNullOrWhiteSpace($text)) {
        return ''
    }

    return ($text -replace '[^A-Z0-9]+', '')
}

function Normalize-StreetFurnitureTerms {
    param([string[]]$Terms)

    $result = New-Object System.Collections.Generic.List[string]
    $seen = @{}
    foreach ($term in $Terms) {
        $text = ([string]$term).Trim()
        if ([string]::IsNullOrWhiteSpace($text)) {
            continue
        }

        $key = Normalize-ComparableText $text
        if ([string]::IsNullOrWhiteSpace($key)) {
            continue
        }

        if ($key -eq 'BOUWAANSLUITING') {
            continue
        }

        if (-not $seen.ContainsKey($key)) {
            $result.Add($text)
            $seen[$key] = $true
        }
    }

    return @($result)
}

function Ensure-StreetFurnitureTermsLoaded {
    if ((Get-CollectionCount $script:StreetFurnitureTerms) -gt 0) {
        return
    }

    $terms = @($script:DefaultStreetFurnitureTerms)
    if ([System.IO.File]::Exists($script:StreetFurnitureTermsConfigPath)) {
        try {
            $content = Get-Content -Path $script:StreetFurnitureTermsConfigPath -Raw -Encoding UTF8
            $json = $content | ConvertFrom-Json
            if ($json -is [System.Array]) {
                $terms = @($json)
            }
            elseif ($null -ne $json.terms) {
                $terms = @($json.terms)
            }
        }
        catch {
            $terms = @($script:DefaultStreetFurnitureTerms)
        }
    }

    $script:StreetFurnitureTerms = @(Normalize-StreetFurnitureTerms -Terms $terms)
}

function Save-StreetFurnitureTerms {
    param([string[]]$Terms)

    $normalizedTerms = @(Normalize-StreetFurnitureTerms -Terms $Terms)
    $payload = [ordered]@{
        terms = $normalizedTerms
        updatedAt = (Get-Date).ToString('s')
    }

    $payload | ConvertTo-Json -Depth 4 | Set-Content -Path $script:StreetFurnitureTermsConfigPath -Encoding UTF8
    $script:StreetFurnitureTerms = $normalizedTerms
    return $normalizedTerms
}

function Test-IsBouwaansluitingUsage {
    param([object]$Row)

    $usageKey = Normalize-ComparableText (Get-ObjectPropertyValue -Object $Row -Name 'Gebruiksdoel')
    if ([string]::IsNullOrWhiteSpace($usageKey)) {
        return $false
    }

    return $usageKey.Contains('BOUWAANSLUITING')
}

function Get-AddressGroupKey {
    param([object]$Row)

    $street = Normalize-ComparableText (Get-ObjectPropertyValue -Object $Row -Name 'Straatnaam')
    $houseNumber = Normalize-HouseNumber (Get-ObjectPropertyValue -Object $Row -Name 'Huisnummer')
    $postcode = Normalize-Postcode (Get-ObjectPropertyValue -Object $Row -Name 'Postcode')
    $city = Normalize-ComparableText (Get-ObjectPropertyValue -Object $Row -Name 'Woonplaats')

    if (-not [string]::IsNullOrWhiteSpace($street) -or -not [string]::IsNullOrWhiteSpace($houseNumber) -or -not [string]::IsNullOrWhiteSpace($postcode) -or -not [string]::IsNullOrWhiteSpace($city)) {
        return ('{0}|{1}|{2}|{3}' -f $street, $houseNumber, $postcode, $city)
    }

    $queryKey = Normalize-ComparableText (Get-ObjectPropertyValue -Object $Row -Name 'AddressQuery')
    if (-not [string]::IsNullOrWhiteSpace($queryKey)) {
        return $queryKey
    }

    return ''
}

function Get-UsageCategory {
    param([object]$Row)

    if (Test-IsBouwaansluitingUsage -Row $Row) {
        return 'service_connection'
    }

    Ensure-StreetFurnitureTermsLoaded

    $usageKey = Normalize-ComparableText (Get-ObjectPropertyValue -Object $Row -Name 'Gebruiksdoel')
    if (-not [string]::IsNullOrWhiteSpace($usageKey)) {
        foreach ($term in $script:StreetFurnitureTerms) {
            $termKey = Normalize-ComparableText $term
            if (-not [string]::IsNullOrWhiteSpace($termKey) -and $usageKey.Contains($termKey)) {
                return 'street_furniture'
            }
        }
    }

    return 'service_connection'
}

function Release-ComObject {
    param($ComObject)

    if ($null -ne $ComObject) {
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($ComObject)
    }
}

function Get-WorksheetByName {
    param(
        $Workbook,
        [string]$Name
    )

    foreach ($worksheet in $Workbook.Worksheets) {
        if ($worksheet.Name -eq $Name) {
            return $worksheet
        }
    }

    return $null
}

function Get-PreferredWorksheetName {
    param([string]$Path)

    $excel = $null
    $workbook = $null

    try {
        $excel = New-Object -ComObject Excel.Application
        $excel.Visible = $false
        $excel.DisplayAlerts = $false
        $workbook = $excel.Workbooks.Open($Path)

        $preferred = Get-WorksheetByName -Workbook $workbook -Name 'Alle stations nieuw'
        if ($preferred) {
            return $preferred.Name
        }

        return [string]$workbook.Worksheets.Item(1).Name
    }
    finally {
        if ($workbook) {
            $workbook.Close($false)
            Release-ComObject $workbook
        }
        if ($excel) {
            $excel.Quit()
            Release-ComObject $excel
        }
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
    }
}

function Read-ExcelRows {
    param(
        [string]$Path,
        [string]$SheetName
    )

    $excel = $null
    $workbook = $null
    $worksheet = $null
    $usedRange = $null
    $values = $null

    try {
        $excel = New-Object -ComObject Excel.Application
        $excel.Visible = $false
        $excel.DisplayAlerts = $false

        $workbook = $excel.Workbooks.Open($Path)
        $worksheet = Get-WorksheetByName -Workbook $workbook -Name $SheetName
        if (-not $worksheet) {
            throw "Werkblad '$SheetName' niet gevonden in '$Path'."
        }

        $usedRange = $worksheet.UsedRange
        $rowCount = [int]$usedRange.Rows.Count
        $columnCount = [int]$usedRange.Columns.Count
        $values = $usedRange.Value2

        $headers = @()
        for ($columnIndex = 1; $columnIndex -le $columnCount; $columnIndex++) {
            $headerValue = [string]$values[1, $columnIndex]
            if ([string]::IsNullOrWhiteSpace($headerValue)) {
                $headerValue = "Column$columnIndex"
            }

            $headers += $headerValue.Trim()
        }

        $rows = New-Object System.Collections.Generic.List[object]
        for ($rowIndex = 2; $rowIndex -le $rowCount; $rowIndex++) {
            $record = [ordered]@{}
            $hasValue = $false

            for ($columnIndex = 1; $columnIndex -le $columnCount; $columnIndex++) {
                $header = $headers[$columnIndex - 1]
                $cellValue = $values[$rowIndex, $columnIndex]
                $cellText = if ($null -eq $cellValue) { '' } else { [string]$cellValue }
                if (-not [string]::IsNullOrWhiteSpace($cellText)) {
                    $hasValue = $true
                }

                $record[$header] = $cellText
            }

            if ($hasValue) {
                $rows.Add([pscustomobject]$record)
            }
        }

        return $rows
    }
    finally {
        if ($usedRange) { Release-ComObject $usedRange }
        if ($worksheet) { Release-ComObject $worksheet }
        if ($workbook) {
            $workbook.Close($false)
            Release-ComObject $workbook
        }
        if ($excel) {
            $excel.Quit()
            Release-ComObject $excel
        }
        [GC]::Collect()
        [GC]::WaitForPendingFinalizers()
    }
}

function Convert-DutchNumberToDouble {
    param($Value)

    if ($null -eq $Value) {
        return $null
    }

    $text = ([string]$Value).Trim()
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }

    try {
        return [double]::Parse($text, [System.Globalization.CultureInfo]::GetCultureInfo('nl-NL'))
    }
    catch {
        return $null
    }
}

function Convert-FlexibleNumberToDouble {
    param($Value)

    if ($null -eq $Value) {
        return $null
    }

    if ($Value -is [double] -or $Value -is [int] -or $Value -is [decimal]) {
        return [double]$Value
    }

    $text = ([string]$Value).Trim()
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }

    if ($text -match '^-?\d+\.\d+$') {
        try {
            return [double]::Parse($text, [System.Globalization.CultureInfo]::InvariantCulture)
        }
        catch {
        }
    }

    if ($text -match '^-?\d+,\d+$') {
        try {
            return [double]::Parse($text, [System.Globalization.CultureInfo]::GetCultureInfo('nl-NL'))
        }
        catch {
        }
    }

    if ($text.Contains(',') -and $text.Contains('.')) {
        $lastComma = $text.LastIndexOf(',')
        $lastDot = $text.LastIndexOf('.')
        if ($lastComma -gt $lastDot) {
            $normalized = ($text -replace '\.', '') -replace ',', '.'
        }
        else {
            $normalized = $text -replace ',', ''
        }

        try {
            return [double]::Parse($normalized, [System.Globalization.CultureInfo]::InvariantCulture)
        }
        catch {
        }
    }

    foreach ($culture in @(
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.CultureInfo]::GetCultureInfo('en-US'),
        [System.Globalization.CultureInfo]::GetCultureInfo('nl-NL')
    )) {
        try {
            return [double]::Parse($text, $culture)
        }
        catch {
        }
    }

    try {
        return [double]::Parse(($text -replace ',', '.'), [System.Globalization.CultureInfo]::InvariantCulture)
    }
    catch {
        return $null
    }
}

function Convert-RdToWgs84 {
    param(
        [double]$X,
        [double]$Y
    )

    $dX = ($X - 155000.0) * 0.00001
    $dY = ($Y - 463000.0) * 0.00001

    $latSeconds =
        (3235.65389 * $dY) +
        (-32.58297 * [math]::Pow($dX, 2)) +
        (-0.2475 * [math]::Pow($dY, 2)) +
        (-0.84978 * [math]::Pow($dX, 2) * $dY) +
        (-0.0655 * [math]::Pow($dY, 3)) +
        (-0.01709 * [math]::Pow($dX, 2) * [math]::Pow($dY, 2)) +
        (-0.00738 * $dX) +
        (0.0053 * [math]::Pow($dX, 4)) +
        (-0.00039 * [math]::Pow($dX, 2) * [math]::Pow($dY, 3)) +
        (0.00033 * [math]::Pow($dX, 4) * $dY) +
        (-0.00012 * $dX * $dY)

    $lonSeconds =
        (5260.52916 * $dX) +
        (105.94684 * $dX * $dY) +
        (2.45656 * $dX * [math]::Pow($dY, 2)) +
        (-0.81885 * [math]::Pow($dX, 3)) +
        (0.05594 * $dX * [math]::Pow($dY, 3)) +
        (-0.05607 * [math]::Pow($dX, 3) * $dY) +
        (0.01199 * $dY) +
        (-0.00256 * [math]::Pow($dX, 3) * [math]::Pow($dY, 2)) +
        (0.00128 * $dX * [math]::Pow($dY, 4)) +
        (0.00022 * [math]::Pow($dY, 2)) +
        (-0.00022 * [math]::Pow($dX, 2)) +
        (0.00026 * [math]::Pow($dX, 5))

    return [pscustomobject]@{
        Latitude = 52.15517440 + ($latSeconds / 3600.0)
        Longitude = 5.38720621 + ($lonSeconds / 3600.0)
    }
}

function Parse-WktPoint {
    param([string]$Wkt)

    if ([string]::IsNullOrWhiteSpace($Wkt)) {
        return $null
    }

    $match = [regex]::Match($Wkt, 'POINT\s*\(\s*(?<x>-?\d+(\.\d+)?)\s+(?<y>-?\d+(\.\d+)?)\s*\)', 'IgnoreCase')
    if (-not $match.Success) {
        return $null
    }

    return [pscustomobject]@{
        X = [double]$match.Groups['x'].Value
        Y = [double]$match.Groups['y'].Value
    }
}

function Read-TextFileLines {
    param([string]$Path)

    try {
        return @(Get-Content -Path $Path -Encoding UTF8)
    }
    catch {
        return @(Get-Content -Path $Path)
    }
}

function Parse-OverdrachtspuntValue {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }

    $match = [regex]::Match(
        $Value,
        'linksonder:\s*(?<x1>-?\d+(,\d+)?)\s*:\s*(?<y1>-?\d+(,\d+)?)\s*m\s*/\s*rechtsboven:\s*(?<x2>-?\d+(,\d+)?)\s*:\s*(?<y2>-?\d+(,\d+)?)\s*m',
        'IgnoreCase'
    )

    if (-not $match.Success) {
        return $null
    }

    $x1 = Convert-DutchNumberToDouble $match.Groups['x1'].Value
    $y1 = Convert-DutchNumberToDouble $match.Groups['y1'].Value
    $x2 = Convert-DutchNumberToDouble $match.Groups['x2'].Value
    $y2 = Convert-DutchNumberToDouble $match.Groups['y2'].Value

    return [pscustomobject]@{
        X1 = $x1
        Y1 = $y1
        X2 = $x2
        Y2 = $y2
        X = $x1
        Y = $y1
        IsExactPoint = (($x1 -eq $x2) -and ($y1 -eq $y2))
    }
}

function Finalize-LovionTextRecord {
    param(
        [hashtable]$Record,
        [System.Collections.Generic.List[object]]$Rows
    )

    if ($null -eq $Record -or (Get-CollectionCount $Record) -eq 0) {
        return
    }

    $ordered = [ordered]@{}
    foreach ($key in $Record.Keys) {
        $ordered[$key] = $Record[$key]
    }

    $Rows.Add([pscustomobject]$ordered)
}

function Parse-LovionTextLines {
    param([string[]]$Lines)

    $rows = New-Object System.Collections.Generic.List[object]
    $current = $null
    $recordNumber = 0

    foreach ($rawLine in $Lines) {
        $line = [string]$rawLine
        $trimmed = $line.Trim()

        if ($trimmed -match '^LS Aansluiting\b') {
            Finalize-LovionTextRecord -Record $current -Rows $rows
            $recordNumber += 1
            $current = [ordered]@{
                _RecordNumber = $recordNumber
                RecordTitle = $trimmed
            }
            continue
        }

        if ($null -eq $current) {
            continue
        }

        if ([string]::IsNullOrWhiteSpace($trimmed)) {
            continue
        }

        if ($trimmed -match '^\((?<date>\d{1,2}-\d{1,2}-\d{4}\s+\d{2}:\d{2}:\d{2})\)$') {
            $current['ExportedAt'] = $Matches['date']
            continue
        }

        if ($trimmed -match '^(?<key>[^:]+):\s*(?<value>.*)$') {
            $current[$Matches['key'].Trim()] = $Matches['value']
            continue
        }

        if (-not $current.Contains('ExportedBy')) {
            $current['ExportedBy'] = $trimmed
        }
    }

    Finalize-LovionTextRecord -Record $current -Rows $rows
    return $rows
}

function ConvertFrom-LovionClipboardTable {
    param([string]$TextContent)

    if ([string]::IsNullOrWhiteSpace($TextContent) -or -not $TextContent.Contains("`t")) {
        return @()
    }

    $defaultHeaders = @(
        'Master Asset ID',
        'Adres',
        'Gemeente',
        'Woonplaats',
        'Straatnaam',
        'Postcode',
        'Huisnummer',
        'Huisnummer even',
        'Status',
        'Aansluitwijze',
        'Aansluitmethode',
        'Gebruiksdoel',
        'Doorlaatwaarde',
        'Maatschappelijke Prioriteit'
    )
    $knownHeaders = @{
        MASTERASSETID = $true
        ADRES = $true
        GEMEENTE = $true
        WOONPLAATS = $true
        STRAATNAAM = $true
        POSTCODE = $true
        HUISNUMMER = $true
        STATUS = $true
        AANSLUITWIJZE = $true
        AANSLUITMETHODE = $true
        GEBRUIKSDOEL = $true
        DOORLAATWAARDE = $true
    }

    $normalizedText = $TextContent -replace "`r`n", "`n"
    $lines = @($normalizedText -split "`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ((Get-CollectionCount $lines) -eq 0) {
        return @()
    }

    $firstFields = @($lines[0] -split "`t", -1)
    $normalizedFirstFields = @($firstFields | ForEach-Object { ([string]$_).ToUpperInvariant() -replace '[^A-Z0-9]+', '' })
    $headerMatches = @($normalizedFirstFields | Where-Object { $knownHeaders.ContainsKey($_) }).Count
    $hasHeader = ($normalizedFirstFields -contains 'MASTERASSETID') -or ($normalizedFirstFields -contains 'ADRES') -or ($headerMatches -ge 2)

    if ($hasHeader) {
        return @($normalizedText | ConvertFrom-Csv -Delimiter "`t")
    }

    $columnCount = $firstFields.Count
    $headers = New-Object System.Collections.Generic.List[string]
    for ($index = 0; $index -lt $columnCount; $index += 1) {
        if ($index -lt $defaultHeaders.Count) {
            $headers.Add($defaultHeaders[$index])
        }
        else {
            $headers.Add(('Column{0}' -f ($index + 1)))
        }
    }
    return @($normalizedText | ConvertFrom-Csv -Delimiter "`t" -Header $headers.ToArray())
}

function ConvertFrom-LovionClipboardContent {
    param([string]$TextContent)

    if ([string]::IsNullOrWhiteSpace($TextContent)) {
        return @()
    }
    if ($TextContent -match '(?im)^\s*LS Aansluiting\b') {
        return @(Parse-LovionTextLines -Lines ($TextContent -split "`r`n|`n"))
    }
    return @(ConvertFrom-LovionClipboardTable -TextContent $TextContent)
}

function Get-ObjectPropertyValue {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($Object -is [System.Data.DataRow]) {
        if ($Object.Table.Columns.Contains($Name)) {
            $value = $Object[$Name]
            if ($value -eq [DBNull]::Value) {
                return $null
            }

            return $value
        }

        return $null
    }

    $property = $Object.PSObject.Properties[$Name]
    if ($property) {
        return $property.Value
    }

    return $null
}

function Get-CandidatePropertyValue {
    param(
        [object]$Object,
        [string[]]$CandidateNames
    )

    foreach ($candidateName in $CandidateNames) {
        if ($Object -is [System.Collections.IDictionary]) {
            if ($Object.Contains($candidateName)) {
                return $Object[$candidateName]
            }
            continue
        }

        $property = $Object.PSObject.Properties[$candidateName]
        if ($property) {
            return $property.Value
        }
    }

    return $null
}

function Test-TrueLike {
    param($Value)

    if ($Value -is [bool]) {
        return [bool]$Value
    }

    $text = ([string]$Value).Trim()
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $false
    }

    switch -Regex ($text.ToUpperInvariant()) {
        '^(TRUE|1|Y|YES|JA)$' { return $true }
        default { return $false }
    }
}

function Get-CollectionCount {
    param($Value)

    if ($null -eq $Value) {
        return 0
    }

    if ($Value -is [System.Collections.ICollection]) {
        return [int]$Value.Count
    }

    $countProperty = $Value.PSObject.Properties['Count']
    if ($countProperty) {
        return [int]$countProperty.Value
    }

    return @($Value).Count
}

function Build-AddressQuery {
    param([object]$Row)

    $street = [string](Get-ObjectPropertyValue -Object $Row -Name 'Straatnaam')
    $houseNumber = [string](Get-ObjectPropertyValue -Object $Row -Name 'Huisnummer')
    $postcode = [string](Get-ObjectPropertyValue -Object $Row -Name 'Postcode')
    $city = [string](Get-ObjectPropertyValue -Object $Row -Name 'Woonplaats')

    $structured = Join-NonEmpty @($street, $houseNumber, $postcode, $city)
    if (-not [string]::IsNullOrWhiteSpace($structured)) {
        return $structured
    }

    return Join-NonEmpty @(
        [string](Get-ObjectPropertyValue -Object $Row -Name 'Adres'),
        [string](Get-ObjectPropertyValue -Object $Row -Name 'Gemeente'),
        [string](Get-ObjectPropertyValue -Object $Row -Name 'Woonplaats')
    )
}

function Escape-SolrPhrase {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return '""'
    }

    $escaped = $Value -replace '\\', '\\\\'
    $escaped = $escaped -replace '"', '\"'
    return ('"{0}"' -f $escaped)
}

function Build-PdokStructuredQuery {
    param(
        [object]$Row,
        [switch]$IgnoreHouseSuffix
    )

    $street = [string](Get-ObjectPropertyValue -Object $Row -Name 'Straatnaam')
    $postcode = Normalize-Postcode (Get-ObjectPropertyValue -Object $Row -Name 'Postcode')
    $city = [string](Get-ObjectPropertyValue -Object $Row -Name 'Woonplaats')
    $houseNumberRaw = [string](Get-ObjectPropertyValue -Object $Row -Name 'Huisnummer')
    $houseNumberDigits = Get-HouseNumberDigits $houseNumberRaw
    $houseNumberFull = Normalize-HouseNumber $houseNumberRaw
    $suffix = ''
    if (-not [string]::IsNullOrWhiteSpace($houseNumberFull) -and -not [string]::IsNullOrWhiteSpace($houseNumberDigits) -and $houseNumberFull.Length -gt $houseNumberDigits.Length) {
        $suffix = $houseNumberFull.Substring($houseNumberDigits.Length)
    }

    $clauses = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($street)) {
        $clauses.Add(('straatnaam:{0}' -f (Escape-SolrPhrase -Value $street.Trim())))
    }
    if (-not [string]::IsNullOrWhiteSpace($houseNumberDigits)) {
        $clauses.Add(('huisnummer:{0}' -f $houseNumberDigits))
    }
    if (-not $IgnoreHouseSuffix -and -not [string]::IsNullOrWhiteSpace($suffix)) {
        if ($suffix -match '^[A-Z]$') {
            $clauses.Add(('huisletter:{0}' -f $suffix))
        }
        elseif ($suffix -match '^\d{1,4}$') {
            $clauses.Add(('huisnummertoevoeging:{0}' -f (Escape-SolrPhrase -Value $suffix)))
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($postcode)) {
        $clauses.Add(('postcode:{0}' -f $postcode))
    }
    if (-not [string]::IsNullOrWhiteSpace($city)) {
        $clauses.Add(('woonplaatsnaam:{0}' -f (Escape-SolrPhrase -Value $city.Trim())))
    }

    if ((Get-CollectionCount $clauses) -gt 0) {
        return ($clauses -join ' and ')
    }

    return Build-AddressQuery -Row $Row
}

function Build-PdokRequestUri {
    param(
        [object]$Row,
        [switch]$IgnoreHouseSuffix,
        [switch]$UseLooseText
    )

    $query = if ($UseLooseText) {
        $street = [string](Get-ObjectPropertyValue -Object $Row -Name 'Straatnaam')
        $houseDigits = Get-HouseNumberDigits (Get-ObjectPropertyValue -Object $Row -Name 'Huisnummer')
        $postcode = Normalize-Postcode (Get-ObjectPropertyValue -Object $Row -Name 'Postcode')
        $city = [string](Get-ObjectPropertyValue -Object $Row -Name 'Woonplaats')
        $fallbackText = Join-NonEmpty @($street, $houseDigits, $postcode, $city)
        if ([string]::IsNullOrWhiteSpace($fallbackText)) {
            Build-AddressQuery -Row $Row
        }
        else {
            $fallbackText
        }
    }
    else {
        Build-PdokStructuredQuery -Row $Row -IgnoreHouseSuffix:$IgnoreHouseSuffix
    }
    if ([string]::IsNullOrWhiteSpace($query)) {
        return ''
    }

    $parameters = New-Object System.Collections.Generic.List[hashtable]
    $parameters.Add(@{ Key = 'q'; Value = $query })
    $parameters.Add(@{ Key = 'fq'; Value = 'type:adres' })
    $parameters.Add(@{ Key = 'fq'; Value = 'bron:BAG' })
    $parameters.Add(@{ Key = 'rows'; Value = '3' })
    $parameters.Add(@{ Key = 'fl'; Value = 'id,weergavenaam,type,straatnaam,straatnaam_verkort,huisnummer,huisletter,huisnummertoevoeging,huis_nlt,postcode,woonplaatsnaam,centroide_ll,centroide_rd,score' })

    $pairs = foreach ($parameter in $parameters) {
        '{0}={1}' -f [System.Uri]::EscapeDataString([string]$parameter.Key), [System.Uri]::EscapeDataString([string]$parameter.Value)
    }

    return ('https://api.pdok.nl/bzk/locatieserver/search/v3_1/free?{0}' -f ($pairs -join '&'))
}

function Build-PdokRequestUris {
    param([object]$Row)

    $uris = New-Object System.Collections.Generic.List[string]
    $seen = @{}

    foreach ($uri in @(
        (Build-PdokRequestUri -Row $Row),
        (Build-PdokRequestUri -Row $Row -IgnoreHouseSuffix),
        (Build-PdokRequestUri -Row $Row -UseLooseText)
    )) {
        if ([string]::IsNullOrWhiteSpace($uri)) {
            continue
        }

        if (-not $seen.ContainsKey($uri)) {
            $uris.Add($uri)
            $seen[$uri] = $true
        }
    }

    return $uris.ToArray()
}

function Convert-HashtableToQueryString {
    param([hashtable]$Parameters)

    $pairs = foreach ($entry in $Parameters.GetEnumerator()) {
        '{0}={1}' -f [System.Uri]::EscapeDataString([string]$entry.Key), [System.Uri]::EscapeDataString([string]$entry.Value)
    }

    return ($pairs -join '&')
}

function Get-WfsFeaturesFromService {
    param(
        [string]$BaseUrl,
        [string]$LayerName,
        $BoundingBox
    )

    if ($null -eq $BoundingBox) {
        return @()
    }

    $parameters = @{
        service = 'WFS'
        version = '2.0.0'
        request = 'GetFeature'
        typeNames = $LayerName
        outputFormat = 'application/json'
        srsName = 'EPSG:28992'
        bbox = '{0},{1},{2},{3},EPSG:28992' -f $BoundingBox.MinX, $BoundingBox.MinY, $BoundingBox.MaxX, $BoundingBox.MaxY
        count = 5000
    }

    $uri = '{0}?{1}' -f $BaseUrl.TrimEnd('?'), (Convert-HashtableToQueryString -Parameters $parameters)
    $response = Invoke-RestMethod -Uri $uri -Method Get -Headers @{ Accept = 'application/json' }
    if ($null -eq $response.features) {
        return @()
    }

    return @($response.features)
}

function Is-NumericCoordinatePair {
    param($Node)

    if ($Node -isnot [System.Array]) {
        return $false
    }

    if ($Node.Length -lt 2) {
        return $false
    }

    return (($Node[0] -is [ValueType]) -and ($Node[1] -is [ValueType]))
}

function Add-CoordinatePairs {
    param(
        $Node,
        [System.Collections.Generic.List[object]]$Pairs
    )

    if ($null -eq $Node) {
        return
    }

    if (Is-NumericCoordinatePair $Node) {
        $Pairs.Add([pscustomobject]@{
            X = [double]$Node[0]
            Y = [double]$Node[1]
        })
        return
    }

    if ($Node -is [System.Array]) {
        foreach ($child in $Node) {
            Add-CoordinatePairs -Node $child -Pairs $Pairs
        }
    }
}

function Get-GeometryCentroid {
    param($Geometry)

    if ($null -eq $Geometry -or $null -eq $Geometry.coordinates) {
        return $null
    }

    $pairs = New-Object System.Collections.Generic.List[object]
    Add-CoordinatePairs -Node $Geometry.coordinates -Pairs $pairs
    if ((Get-CollectionCount $pairs) -eq 0) {
        return $null
    }

    return [pscustomobject]@{
        X = [double](($pairs | Measure-Object -Property X -Average).Average)
        Y = [double](($pairs | Measure-Object -Property Y -Average).Average)
    }
}

function Measure-RdDistance {
    param(
        [double]$X1,
        [double]$Y1,
        [double]$X2,
        [double]$Y2
    )

    return [math]::Sqrt(([math]::Pow($X2 - $X1, 2)) + ([math]::Pow($Y2 - $Y1, 2)))
}

function Get-NearestWfsFeature {
    param(
        [object[]]$Features,
        [double]$BaseX,
        [double]$BaseY,
        [double]$MaxDistanceMeters = [double]::PositiveInfinity
    )

    $featureList = @($Features)
    if ((Get-CollectionCount $featureList) -eq 0) {
        return $null
    }

    $nearest = $featureList |
        ForEach-Object {
            [pscustomobject]@{
                Feature = $_
                Distance = Measure-RdDistance -X1 $BaseX -Y1 $BaseY -X2 $_.RdX -Y2 $_.RdY
            }
        } |
        Sort-Object Distance |
        Select-Object -First 1

    if ($null -eq $nearest -or $nearest.Distance -gt $MaxDistanceMeters) {
        return $null
    }

    return $nearest
}

function New-BoundingBoxFromRows {
    param(
        [object[]]$Rows,
        [int]$BufferMeters
    )

    $points = New-Object System.Collections.Generic.List[object]
    foreach ($row in $Rows) {
        $seed = Get-SeedRdPoint -Row $row
        if ($null -ne $seed) {
            $points.Add($seed)
        }
    }

    if ((Get-CollectionCount $points) -eq 0) {
        return $null
    }

    return [pscustomobject]@{
        MinX = [double](($points | Measure-Object -Property X -Minimum).Minimum - $BufferMeters)
        MinY = [double](($points | Measure-Object -Property Y -Minimum).Minimum - $BufferMeters)
        MaxX = [double](($points | Measure-Object -Property X -Maximum).Maximum + $BufferMeters)
        MaxY = [double](($points | Measure-Object -Property Y -Maximum).Maximum + $BufferMeters)
    }
}

function Prepare-WfsFeatures {
    param(
        [object[]]$RawFeatures,
        [string]$LayerCategory,
        [string]$LayerName
    )

    $prepared = New-Object System.Collections.Generic.List[object]
    foreach ($feature in $RawFeatures) {
        $centroid = Get-GeometryCentroid -Geometry $feature.geometry
        if ($null -eq $centroid) {
            continue
        }

        $properties = $feature.properties
        $description = [string](Get-CandidatePropertyValue -Object $properties -CandidateNames @('omschrijving', 'label', 'appurtenancetype'))
        $prepared.Add([pscustomobject]@{
            FeatureId = [string]$feature.id
            GeometryType = [string]$feature.geometry.type
            RdX = [double]$centroid.X
            RdY = [double]$centroid.Y
            LayerCategory = $LayerCategory
            LayerName = $LayerName
            Description = $description
            DescriptionKey = Normalize-ComparableText $description
            Properties = $properties
        })
    }

    return $prepared.ToArray()
}

function Get-SeedRdPoint {
    param([object]$Row)

    $x = Convert-FlexibleNumberToDouble (Get-ObjectPropertyValue -Object $Row -Name 'PdokRdX')
    $y = Convert-FlexibleNumberToDouble (Get-ObjectPropertyValue -Object $Row -Name 'PdokRdY')
    if ($null -eq $x -or $null -eq $y) {
        $x = Convert-FlexibleNumberToDouble (Get-ObjectPropertyValue -Object $Row -Name 'FinalRdX')
        $y = Convert-FlexibleNumberToDouble (Get-ObjectPropertyValue -Object $Row -Name 'FinalRdY')
    }

    if ($null -eq $x -or $null -eq $y) {
        return $null
    }

    return [pscustomobject]@{
        X = [double]$x
        Y = [double]$y
    }
}

function Get-ExportPointForRow {
    param([object]$Row)

    $x = Convert-FlexibleNumberToDouble (Get-ObjectPropertyValue -Object $Row -Name 'OverdrachtspuntRdX1')
    $y = Convert-FlexibleNumberToDouble (Get-ObjectPropertyValue -Object $Row -Name 'OverdrachtspuntRdY1')
    if ($null -eq $x -or $null -eq $y) {
        $x = Convert-FlexibleNumberToDouble (Get-ObjectPropertyValue -Object $Row -Name 'FinalRdX')
        $y = Convert-FlexibleNumberToDouble (Get-ObjectPropertyValue -Object $Row -Name 'FinalRdY')
    }

    if ($null -eq $x -or $null -eq $y) {
        return $null
    }

    return [pscustomobject]@{
        X = [double]$x
        Y = [double]$y
    }
}

function Get-WfsFeaturePointKey {
    param([object]$Feature)

    return ('{0:0.###}|{1:0.###}' -f [double]$Feature.RdX, [double]$Feature.RdY)
}

function Get-WfsSpatialCellKey {
    param(
        [double]$X,
        [double]$Y,
        [double]$CellSize
    )

    $cellX = [int][math]::Floor($X / $CellSize)
    $cellY = [int][math]::Floor($Y / $CellSize)
    return ('{0}|{1}' -f $cellX, $cellY)
}

function New-WfsSpatialIndex {
    param(
        [object[]]$Features,
        [double]$CellSize
    )

    if ($CellSize -le 0) {
        $CellSize = 25
    }

    $bucketMap = @{}
    foreach ($feature in $Features) {
        $bucketKey = Get-WfsSpatialCellKey -X ([double]$feature.RdX) -Y ([double]$feature.RdY) -CellSize $CellSize
        if (-not $bucketMap.ContainsKey($bucketKey)) {
            $bucketMap[$bucketKey] = New-Object System.Collections.Generic.List[object]
        }

        $bucketMap[$bucketKey].Add($feature)
    }

    return [pscustomobject]@{
        CellSize = [double]$CellSize
        Buckets = $bucketMap
        Features = @($Features)
    }
}

function Get-WfsNearbyFeatureCacheKey {
    param(
        [double]$BaseX,
        [double]$BaseY,
        [double]$SearchRadius
    )

    return ('{0:0.###}|{1:0.###}|{2:0.###}' -f $BaseX, $BaseY, $SearchRadius)
}

function Get-WfsNearbyFeatures {
    param(
        [object]$SpatialIndex,
        [double]$BaseX,
        [double]$BaseY,
        [double]$SearchRadius,
        [hashtable]$Cache
    )

    if ($null -eq $SpatialIndex) {
        return @()
    }

    $cacheKey = Get-WfsNearbyFeatureCacheKey -BaseX $BaseX -BaseY $BaseY -SearchRadius $SearchRadius
    if ($null -ne $Cache -and $Cache.ContainsKey($cacheKey)) {
        return @($Cache[$cacheKey])
    }

    if ([double]::IsPositiveInfinity($SearchRadius)) {
        $allFeatures = @($SpatialIndex.Features)
        if ($null -ne $Cache) {
            $Cache[$cacheKey] = $allFeatures
        }

        return $allFeatures
    }

    $cellSize = [double]$SpatialIndex.CellSize
    $centerCellX = [int][math]::Floor($BaseX / $cellSize)
    $centerCellY = [int][math]::Floor($BaseY / $cellSize)
    $cellRadius = [int][math]::Ceiling($SearchRadius / $cellSize)
    $nearby = New-Object System.Collections.Generic.List[object]

    for ($cellX = $centerCellX - $cellRadius; $cellX -le $centerCellX + $cellRadius; $cellX++) {
        for ($cellY = $centerCellY - $cellRadius; $cellY -le $centerCellY + $cellRadius; $cellY++) {
            $bucketKey = ('{0}|{1}' -f $cellX, $cellY)
            if (-not $SpatialIndex.Buckets.ContainsKey($bucketKey)) {
                continue
            }

            foreach ($feature in $SpatialIndex.Buckets[$bucketKey]) {
                $nearby.Add($feature)
            }
        }
    }

    $nearbyFeatures = $nearby.ToArray()
    if ($null -ne $Cache) {
        $Cache[$cacheKey] = $nearbyFeatures
    }

    return $nearbyFeatures
}

function Get-WfsCandidatesByDistance {
    param(
        [object[]]$Features,
        [double]$BaseX,
        [double]$BaseY,
        [double]$MaxDistanceMeters = [double]::PositiveInfinity
    )

    $featureList = @($Features)
    if ((Get-CollectionCount $featureList) -eq 0) {
        return @()
    }

    return @(
        $featureList |
            ForEach-Object {
                [pscustomobject]@{
                    Feature = $_
                    Distance = Measure-RdDistance -X1 $BaseX -Y1 $BaseY -X2 $_.RdX -Y2 $_.RdY
                }
            } |
            Where-Object { $_.Distance -le $MaxDistanceMeters } |
            Sort-Object Distance
    )
}

function Select-FirstAvailableWfsCandidate {
    param(
        [object[]]$Candidates,
        [hashtable]$UsedFeatureIds,
        [hashtable]$UsedPointKeys,
        [string]$MatchMode,
        [string]$ExhaustedMatchMode
    )

    $candidateList = @($Candidates)
    $hadCandidates = $false

    foreach ($candidate in $candidateList) {
        $hadCandidates = $true
        $featureId = [string]$candidate.Feature.FeatureId
        $pointKey = Get-WfsFeaturePointKey -Feature $candidate.Feature
        if (($UsedFeatureIds.ContainsKey($featureId)) -or ($UsedPointKeys.ContainsKey($pointKey))) {
            continue
        }

        return [pscustomobject]@{
            Feature = $candidate.Feature
            Distance = $candidate.Distance
            MatchMode = $MatchMode
            IsUniqueExhausted = $false
        }
    }

    if ($hadCandidates) {
        return [pscustomobject]@{
            Feature = $null
            Distance = $null
            MatchMode = $ExhaustedMatchMode
            IsUniqueExhausted = $true
        }
    }

    return $null
}

function Select-WfsServiceConnectionFeatureForRow {
    param(
        [object]$Row,
        [object[]]$Features,
        [object]$SpatialIndex,
        [double]$BaseX,
        [double]$BaseY,
        [double]$MaxDistanceMeters,
        [hashtable]$UsedFeatureIds,
        [hashtable]$UsedPointKeys,
        [hashtable]$NearbyCache
    )

    $candidateFeatures = if ($null -ne $SpatialIndex) {
        Get-WfsNearbyFeatures -SpatialIndex $SpatialIndex -BaseX $BaseX -BaseY $BaseY -SearchRadius $MaxDistanceMeters -Cache $NearbyCache
    }
    else {
        $Features
    }

    $candidates = Get-WfsCandidatesByDistance -Features $candidateFeatures -BaseX $BaseX -BaseY $BaseY -MaxDistanceMeters $MaxDistanceMeters
    return Select-FirstAvailableWfsCandidate -Candidates $candidates -UsedFeatureIds $UsedFeatureIds -UsedPointKeys $UsedPointKeys -MatchMode 'service_connection_nearest' -ExhaustedMatchMode 'service_connection_point_already_used'
}

function Select-WfsStreetFurnitureFeatureForRow {
    param(
        [object]$Row,
        [object[]]$Features,
        [object]$SpatialIndex,
        [double]$BaseX,
        [double]$BaseY,
        [double]$MaxDistanceMeters,
        [hashtable]$UsedFeatureIds,
        [hashtable]$UsedPointKeys,
        [hashtable]$NearbyCache
    )

    $usage = [string](Get-ObjectPropertyValue -Object $Row -Name 'Gebruiksdoel')
    $usageKey = Normalize-ComparableText $usage
    $hadUsedOnlyCandidates = $false
    $candidateFeatures = if ($null -ne $SpatialIndex) {
        @(Get-WfsNearbyFeatures -SpatialIndex $SpatialIndex -BaseX $BaseX -BaseY $BaseY -SearchRadius $MaxDistanceMeters -Cache $NearbyCache)
    }
    else {
        @($Features)
    }

    if (-not [string]::IsNullOrWhiteSpace($usageKey)) {
        $exactMatches = @($candidateFeatures | Where-Object { $_.DescriptionKey -eq $usageKey })
        if ((Get-CollectionCount $exactMatches) -gt 0) {
            $exactCandidates = Get-WfsCandidatesByDistance -Features $exactMatches -BaseX $BaseX -BaseY $BaseY -MaxDistanceMeters $MaxDistanceMeters
            $exactSelection = Select-FirstAvailableWfsCandidate -Candidates $exactCandidates -UsedFeatureIds $UsedFeatureIds -UsedPointKeys $UsedPointKeys -MatchMode 'street_furniture_description_exact' -ExhaustedMatchMode 'street_furniture_point_already_used'
            if ($null -ne $exactSelection) {
                if ($null -ne $exactSelection.Feature) {
                    return $exactSelection
                }
                if ($exactSelection.IsUniqueExhausted) {
                    $hadUsedOnlyCandidates = $true
                }
            }
        }

        $partialMatches = @(
            $candidateFeatures |
                Where-Object {
                    -not [string]::IsNullOrWhiteSpace($_.DescriptionKey) -and (
                        $_.DescriptionKey.Contains($usageKey) -or
                        $usageKey.Contains($_.DescriptionKey)
                    )
                }
        )
        if ((Get-CollectionCount $partialMatches) -gt 0) {
            $partialCandidates = Get-WfsCandidatesByDistance -Features $partialMatches -BaseX $BaseX -BaseY $BaseY -MaxDistanceMeters $MaxDistanceMeters
            $partialSelection = Select-FirstAvailableWfsCandidate -Candidates $partialCandidates -UsedFeatureIds $UsedFeatureIds -UsedPointKeys $UsedPointKeys -MatchMode 'street_furniture_description_partial' -ExhaustedMatchMode 'street_furniture_point_already_used'
            if ($null -ne $partialSelection) {
                if ($null -ne $partialSelection.Feature) {
                    return $partialSelection
                }
                if ($partialSelection.IsUniqueExhausted) {
                    $hadUsedOnlyCandidates = $true
                }
            }
        }
    }

    $anyCandidates = Get-WfsCandidatesByDistance -Features $candidateFeatures -BaseX $BaseX -BaseY $BaseY -MaxDistanceMeters $MaxDistanceMeters
    $anySelection = Select-FirstAvailableWfsCandidate -Candidates $anyCandidates -UsedFeatureIds $UsedFeatureIds -UsedPointKeys $UsedPointKeys -MatchMode 'street_furniture_nearest' -ExhaustedMatchMode 'street_furniture_point_already_used'
    if ($null -ne $anySelection) {
        return $anySelection
    }

    if ($hadUsedOnlyCandidates) {
        return [pscustomobject]@{
            Feature = $null
            Distance = $null
            MatchMode = 'street_furniture_point_already_used'
            IsUniqueExhausted = $true
        }
    }

    return $null
}

function Get-SourceFileDisplayName {
    param([string]$Name)

    if ([string]::IsNullOrWhiteSpace($Name)) {
        return ''
    }

    $trimmed = $Name.Trim()
    try {
        $fileName = [System.IO.Path]::GetFileName($trimmed)
        return ($fileName -replace '\.(txt|csv|xlsx|xls|geojson|json|shp)$', '')
    }
    catch {
        return $trimmed
    }
}

function Test-IsPdokToleratedReason {
    param([string]$Reason)

    return (([string]$Reason).Trim() -eq 'house_suffix_mismatch')
}

function New-PreparedRowObject {
    param(
        [object]$Row,
        [string]$SourceFile,
        [string]$SourcePath,
        [string]$SourceType
    )

    $record = [ordered]@{}
    if ($Row -is [System.Data.DataRow]) {
        foreach ($column in $Row.Table.Columns) {
            $value = $Row[$column.ColumnName]
            if ($value -eq [DBNull]::Value) {
                $record[$column.ColumnName] = $null
            }
            else {
                $record[$column.ColumnName] = [string]$value
            }
        }
    }
    else {
        foreach ($property in $Row.PSObject.Properties) {
            if ($property.Name -like '_*') {
                continue
            }

            $record[$property.Name] = $property.Value
        }
    }

    $record['SourceFile'] = Get-SourceFileDisplayName $SourceFile
    $record['SourcePath'] = $SourcePath
    $record['SourceType'] = $SourceType

    if ([string]::IsNullOrWhiteSpace([string]$record['AddressQuery'])) {
        $record['AddressQuery'] = Build-AddressQuery -Row ([pscustomobject]$record)
    }

    $record['UsageCategory'] = Get-UsageCategory -Row ([pscustomobject]$record)

    $finalX = Convert-FlexibleNumberToDouble $record['FinalRdX']
    $finalY = Convert-FlexibleNumberToDouble $record['FinalRdY']

    if ($null -eq $finalX -or $null -eq $finalY) {
        $parsedPoint = Parse-OverdrachtspuntValue ([string]$record['Overdrachtspunt'])
        if ($parsedPoint) {
            $record['OverdrachtspuntRdX1'] = $parsedPoint.X1
            $record['OverdrachtspuntRdY1'] = $parsedPoint.Y1
            $record['OverdrachtspuntRdX2'] = $parsedPoint.X2
            $record['OverdrachtspuntRdY2'] = $parsedPoint.Y2
            $record['OverdrachtspuntIsPoint'] = $parsedPoint.IsExactPoint
            $record['FinalRdX'] = $parsedPoint.X1
            $record['FinalRdY'] = $parsedPoint.Y1
            $record['CoordinateSource'] = if ([string]::IsNullOrWhiteSpace([string]$record['CoordinateSource'])) { 'overdrachtspunt_text' } else { $record['CoordinateSource'] }
            $record['MatchStatus'] = if ([string]::IsNullOrWhiteSpace([string]$record['MatchStatus'])) {
                if ($parsedPoint.IsExactPoint) { 'overdrachtspunt_exact' } else { 'overdrachtspunt_centroid' }
            }
            else {
                $record['MatchStatus']
            }
            $finalX = $parsedPoint.X1
            $finalY = $parsedPoint.Y1
        }
    }

    $pdokStrictMatch = $false
    if ($record.Contains('PdokStrictMatch')) {
        $pdokStrictMatch = Test-TrueLike $record['PdokStrictMatch']
    }

    $pdokMatchReason = ''
    if ($record.Contains('PdokMatchReason')) {
        $pdokMatchReason = [string]$record['PdokMatchReason']
    }

    $pdokTolerantMatch = Test-IsPdokToleratedReason -Reason $pdokMatchReason
    $pdokAcceptedMatch = ($pdokStrictMatch -or $pdokTolerantMatch)
    $usedPdokCoordinates = $false

    if (($null -eq $finalX -or $null -eq $finalY) -and $pdokAcceptedMatch -and $record.Contains('PdokRdX') -and $record.Contains('PdokRdY')) {
        $finalX = Convert-FlexibleNumberToDouble $record['PdokRdX']
        $finalY = Convert-FlexibleNumberToDouble $record['PdokRdY']
        if ($null -ne $finalX -and $null -ne $finalY) {
            $record['FinalRdX'] = $finalX
            $record['FinalRdY'] = $finalY
            $usedPdokCoordinates = $true
        }
    }

    if ($null -ne $finalX -and $null -ne $finalY) {
        if ([string]::IsNullOrWhiteSpace([string]$record['FinalLon']) -or [string]::IsNullOrWhiteSpace([string]$record['FinalLat'])) {
            $wgs84 = Convert-RdToWgs84 -X $finalX -Y $finalY
            $record['FinalLon'] = [math]::Round([double]$wgs84.Longitude, 8)
            $record['FinalLat'] = [math]::Round([double]$wgs84.Latitude, 8)
        }

        if ($usedPdokCoordinates) {
            if ([string]::IsNullOrWhiteSpace([string]$record['CoordinateSource'])) {
                $record['CoordinateSource'] = if ($pdokStrictMatch) { 'pdok' } else { 'pdok_tolerant' }
            }
            if ([string]::IsNullOrWhiteSpace([string]$record['MatchStatus'])) {
                $record['MatchStatus'] = if ($pdokStrictMatch) { 'pdok_exact' } else { 'pdok_tolerant_house_suffix' }
            }
        }

        if ([string]::IsNullOrWhiteSpace([string]$record['CoordinateSource'])) {
            $record['CoordinateSource'] = 'manual'
        }
        if ([string]::IsNullOrWhiteSpace([string]$record['MatchStatus'])) {
            $record['MatchStatus'] = 'manual'
        }
    }

    return [pscustomobject]$record
}

function Add-TableColumn {
    param([string]$Name)

    if (-not $script:Table.Columns.Contains($Name)) {
        $column = New-Object System.Data.DataColumn($Name, [string])
        [void]$script:Table.Columns.Add($column)
    }
}

function Ensure-PreferredColumnOrder {
    $preferredColumns = @(
        'SourceFile',
        'SourceType',
        'RecordTitle',
        'Master Asset ID',
        'Adres',
        'Straatnaam',
        'Huisnummer',
        'Postcode',
        'Woonplaats',
        'Gebruiksdoel',
        'UsageCategory',
        'AddressQuery',
        'PdokDisplayName',
        'PdokType',
        'PdokScore',
        'PdokRdX',
        'PdokRdY',
        'PdokLon',
        'PdokLat',
        'PdokStrictMatch',
        'PdokMatchReason',
        'WfsLayer',
        'WfsDescription',
        'WfsFeatureId',
        'WfsMatchMode',
        'WfsDistanceM',
        'Overdrachtspunt',
        'FinalRdX',
        'FinalRdY',
        'FinalLon',
        'FinalLat',
        'CoordinateSource',
        'MatchStatus'
    )

    $ordinal = 0
    foreach ($columnName in $preferredColumns) {
        if ($script:Table.Columns.Contains($columnName)) {
            $script:Table.Columns[$columnName].SetOrdinal($ordinal)
            $ordinal += 1
        }
    }
}

function Apply-GridColumnHeaders {
    if (-not $script:Grid) {
        return
    }

    $headerMap = @{
        SourceFile = 'SourceFile'
        SourceType = 'Bron'
        RecordTitle = 'Record'
        UsageCategory = 'UsageCategory'
        AddressQuery = 'Adresquery'
        PdokDisplayName = 'PDOK Naam'
        PdokType = 'PDOK Type'
        PdokScore = 'PDOK Score'
        PdokRdX = 'PDOK RD X'
        PdokRdY = 'PDOK RD Y'
        PdokLon = 'PDOK Lon'
        PdokLat = 'PDOK Lat'
        PdokStrictMatch = 'PDOK Exact'
        PdokMatchReason = 'PDOK Reden'
        WfsLayer = 'Enexis Layer'
        WfsDescription = 'Enexis Omschr.'
        WfsFeatureId = 'Enexis Feature'
        WfsMatchMode = 'Enexis Match'
        WfsDistanceM = 'Enexis Afst. m'
        FinalRdX = 'Final RD X'
        FinalRdY = 'Final RD Y'
        FinalLon = 'Final Lon'
        FinalLat = 'Final Lat'
        CoordinateSource = 'Coord Bron'
        MatchStatus = 'Status'
    }

    foreach ($name in $headerMap.Keys) {
        if ($script:Grid.Columns.Contains($name)) {
            $script:Grid.Columns[$name].HeaderText = $headerMap[$name]
        }
    }
}

function Ensure-TableColumnsForRow {
    param([pscustomobject]$Row)

    foreach ($property in $Row.PSObject.Properties) {
        Add-TableColumn -Name $property.Name
    }

    Ensure-PreferredColumnOrder
}

function Update-StatusBar {
    if (-not $script:StatusLabel) {
        return
    }

    $total = 0
    $withCoords = 0
    foreach ($row in $script:Table.Rows) {
        if ($row.RowState -eq [System.Data.DataRowState]::Deleted) {
            continue
        }

        $total += 1
        $x = $row['FinalRdX']
        $y = $row['FinalRdY']
        if ($x -ne [DBNull]::Value -and $y -ne [DBNull]::Value -and -not [string]::IsNullOrWhiteSpace([string]$x) -and -not [string]::IsNullOrWhiteSpace([string]$y)) {
            $withCoords += 1
        }
    }

    $script:StatusLabel.Text = "Rijen: $total | Met coordinaten: $withCoords"
}

function Add-RowsToTable {
    param([object[]]$Rows)

    foreach ($row in $Rows) {
        Ensure-TableColumnsForRow -Row $row
        $dataRow = $script:Table.NewRow()
        foreach ($property in $row.PSObject.Properties) {
            $value = $property.Value
            if ($null -eq $value) {
                $dataRow[$property.Name] = [DBNull]::Value
            }
            else {
                $dataRow[$property.Name] = [string]$value
            }
        }
        $script:Table.Rows.Add($dataRow)
    }

    if ($script:Grid) {
        if ($script:Grid.Columns.Contains('SourcePath')) {
            $script:Grid.Columns['SourcePath'].Visible = $false
        }
        if ($script:Grid.Columns.Contains('_RecordNumber')) {
            $script:Grid.Columns['_RecordNumber'].Visible = $false
        }
        Apply-GridColumnHeaders
    }

    Update-StatusBar
}

function Convert-DataTableRowsToObjects {
    param([System.Data.DataTable]$Table)

    $rows = New-Object System.Collections.Generic.List[object]
    foreach ($dataRow in $Table.Rows) {
        if ($dataRow.RowState -eq [System.Data.DataRowState]::Deleted) {
            continue
        }

        $record = [ordered]@{}
        $hasValue = $false
        foreach ($column in $Table.Columns) {
            $value = $dataRow[$column.ColumnName]
            if ($value -eq [DBNull]::Value) {
                $record[$column.ColumnName] = $null
            }
            else {
                $text = [string]$value
                if (-not [string]::IsNullOrWhiteSpace($text)) {
                    $hasValue = $true
                }
                $record[$column.ColumnName] = $text
            }
        }

        if ($hasValue) {
            $prepared = New-PreparedRowObject -Row ([pscustomobject]$record) -SourceFile ([string]$record['SourceFile']) -SourcePath ([string]$record['SourcePath']) -SourceType ([string]$record['SourceType'])
            $rows.Add($prepared)
        }
    }

    return $rows
}

function Update-TableFromPreparedRows {
    param([object[]]$Rows)

    $script:Table.Rows.Clear()
    Add-RowsToTable -Rows $Rows
}

function Show-InfoMessage {
    param([string]$Message)
    [void][System.Windows.Forms.MessageBox]::Show($script:MainForm, $Message, $script:AppName, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)
}

function Show-ErrorMessage {
    param([string]$Message)
    [void][System.Windows.Forms.MessageBox]::Show($script:MainForm, $Message, $script:AppName, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
}

function Search-PdokAddress {
    param(
        [string]$Query,
        [string]$RequestUri
    )

    if ([string]::IsNullOrWhiteSpace($RequestUri) -and [string]::IsNullOrWhiteSpace($Query)) {
        return @()
    }

    $uri = if ([string]::IsNullOrWhiteSpace($RequestUri)) {
        Get-PdokSearchUri -Query $Query
    }
    else {
        $RequestUri
    }
    $response = Invoke-RestMethod -Uri $uri -Method Get -Headers @{ Accept = 'application/json' }

    $docs = @($response.response.docs)
    if ($null -eq $response.response -or (Get-CollectionCount $docs) -eq 0) {
        return @()
    }

    return $docs
}

function Get-PdokSearchUri {
    param(
        [string]$Query,
        [int]$Rows = 10
    )

    $encodedQuery = [System.Uri]::EscapeDataString($Query)
    return "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free?q=$encodedQuery&rows=$Rows"
}

function Convert-PdokJsonToDocs {
    param([string]$Json)

    if ([string]::IsNullOrWhiteSpace($Json)) {
        return @()
    }

    try {
        $response = $Json | ConvertFrom-Json
    }
    catch {
        return @()
    }

    $docs = @($response.response.docs)
    if ($null -eq $response.response -or (Get-CollectionCount $docs) -eq 0) {
        return @()
    }

    return $docs
}

function Invoke-PdokQueryBatch {
    param(
        [string[]]$Queries,
        [int]$MaxConcurrency = 6,
        [int]$DelayBetweenDispatchMs = 0,
        [scriptblock]$OnProgress
    )

    $queryList = @($Queries | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $cache = @{}
    if ((Get-CollectionCount $queryList) -eq 0) {
        return $cache
    }

    if ($MaxConcurrency -le 1) {
        $completed = 0
        foreach ($query in $queryList) {
            try {
                if ($query -like 'http*://*') {
                    $cache[$query] = @(Search-PdokAddress -RequestUri $query)
                }
                else {
                    $cache[$query] = @(Search-PdokAddress -Query $query)
                }
            }
            catch {
                $cache[$query] = @()
            }

            $completed += 1
            if ($OnProgress) {
                & $OnProgress $completed (Get-CollectionCount $queryList) $query
            }

            if ($DelayBetweenDispatchMs -gt 0 -and $completed -lt (Get-CollectionCount $queryList)) {
                Start-Sleep -Milliseconds $DelayBetweenDispatchMs
            }
        }

        return $cache
    }

    [System.Net.ServicePointManager]::DefaultConnectionLimit = [Math]::Max([System.Net.ServicePointManager]::DefaultConnectionLimit, ($MaxConcurrency * 2))

    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromSeconds(30)
    $client.DefaultRequestHeaders.Accept.Clear()
    [void]$client.DefaultRequestHeaders.Accept.Add([System.Net.Http.Headers.MediaTypeWithQualityHeaderValue]::new('application/json'))

    $pending = New-Object System.Collections.ArrayList
    $nextIndex = 0
    $completed = 0

    try {
        while ($nextIndex -lt (Get-CollectionCount $queryList) -or $pending.Count -gt 0) {
            while ($nextIndex -lt (Get-CollectionCount $queryList) -and $pending.Count -lt $MaxConcurrency) {
                $query = [string]$queryList[$nextIndex]
                $uri = if ($query -like 'http*://*') { $query } else { Get-PdokSearchUri -Query $query }
                $task = $client.GetStringAsync($uri)
                [void]$pending.Add([pscustomobject]@{
                    Query = $query
                    Task = $task
                })

                $nextIndex += 1
                if ($DelayBetweenDispatchMs -gt 0 -and $pending.Count -lt $MaxConcurrency -and $nextIndex -lt (Get-CollectionCount $queryList)) {
                    Start-Sleep -Milliseconds $DelayBetweenDispatchMs
                }
            }

            if ($pending.Count -eq 0) {
                continue
            }

            $tasks = [System.Threading.Tasks.Task[]]@($pending | ForEach-Object { [System.Threading.Tasks.Task]$_.Task })
            $completedIndex = [System.Threading.Tasks.Task]::WaitAny($tasks)
            if ($completedIndex -lt 0) {
                continue
            }

            $item = $pending[$completedIndex]
            $pending.RemoveAt($completedIndex)

            $query = [string]$item.Query
            try {
                $json = $item.Task.GetAwaiter().GetResult()
                $cache[$query] = @(Convert-PdokJsonToDocs -Json $json)
            }
            catch {
                $cache[$query] = @()
            }

            $completed += 1
            if ($OnProgress) {
                & $OnProgress $completed (Get-CollectionCount $queryList) $query
            }
        }
    }
    finally {
        $client.Dispose()
    }

    return $cache
}

function Convert-PdokDocToCandidate {
    param($Doc)

    $rdPoint = Parse-WktPoint (Get-CandidatePropertyValue -Object $Doc -CandidateNames @('centroide_rd'))
    $llPoint = Parse-WktPoint (Get-CandidatePropertyValue -Object $Doc -CandidateNames @('centroide_ll'))
    $fullHouseNumber = Normalize-HouseNumber (Get-CandidatePropertyValue -Object $Doc -CandidateNames @('huis_nlt'))
    if ([string]::IsNullOrWhiteSpace($fullHouseNumber)) {
        $fullHouseNumber = Normalize-HouseNumber ("{0}{1}" -f [string](Get-CandidatePropertyValue -Object $Doc -CandidateNames @('huisnummer')), [string](Get-CandidatePropertyValue -Object $Doc -CandidateNames @('huisletter')))
    }

    return [pscustomobject]@{
        Id = [string](Get-CandidatePropertyValue -Object $Doc -CandidateNames @('id'))
        DisplayName = [string](Get-CandidatePropertyValue -Object $Doc -CandidateNames @('weergavenaam'))
        Type = [string](Get-CandidatePropertyValue -Object $Doc -CandidateNames @('type'))
        Score = [double](Get-CandidatePropertyValue -Object $Doc -CandidateNames @('score'))
        Street = Normalize-Text (Get-CandidatePropertyValue -Object $Doc -CandidateNames @('straatnaam'))
        StreetShort = Normalize-Text (Get-CandidatePropertyValue -Object $Doc -CandidateNames @('straatnaam_verkort'))
        Postcode = Normalize-Postcode (Get-CandidatePropertyValue -Object $Doc -CandidateNames @('postcode'))
        City = Normalize-Text (Get-CandidatePropertyValue -Object $Doc -CandidateNames @('woonplaatsnaam'))
        HouseNumber = Get-HouseNumberDigits (Get-CandidatePropertyValue -Object $Doc -CandidateNames @('huisnummer'))
        HouseNumberFull = $fullHouseNumber
        RdX = if ($rdPoint) { [double]$rdPoint.X } else { $null }
        RdY = if ($rdPoint) { [double]$rdPoint.Y } else { $null }
        Lon = if ($llPoint) { [double]$llPoint.X } else { $null }
        Lat = if ($llPoint) { [double]$llPoint.Y } else { $null }
    }
}

function Select-PdokCandidateForRow {
    param(
        [object]$Row,
        [object[]]$Docs
    )

    if ((Get-CollectionCount $Docs) -eq 0) {
        return $null
    }

    $expectedStreet = Normalize-Text (Get-ObjectPropertyValue -Object $Row -Name 'Straatnaam')
    $expectedPostcode = Normalize-Postcode (Get-ObjectPropertyValue -Object $Row -Name 'Postcode')
    $expectedCity = Normalize-Text (Get-ObjectPropertyValue -Object $Row -Name 'Woonplaats')
    $expectedHouseNumber = Normalize-HouseNumber (Get-ObjectPropertyValue -Object $Row -Name 'Huisnummer')
    $expectedHouseDigits = Get-HouseNumberDigits (Get-ObjectPropertyValue -Object $Row -Name 'Huisnummer')

    $candidates = foreach ($doc in $Docs) {
        $candidate = Convert-PdokDocToCandidate -Doc $doc
        $streetMatches = $false
        if (-not [string]::IsNullOrWhiteSpace($expectedStreet)) {
            $streetMatches =
                ($candidate.Street -eq $expectedStreet) -or
                ($candidate.StreetShort -eq $expectedStreet)
        }

        $postcodeMatches = [string]::IsNullOrWhiteSpace($expectedPostcode) -or ($candidate.Postcode -eq $expectedPostcode)
        $cityMatches = [string]::IsNullOrWhiteSpace($expectedCity) -or ($candidate.City -eq $expectedCity)
        $houseDigitsMatch = [string]::IsNullOrWhiteSpace($expectedHouseDigits) -or ($candidate.HouseNumber -eq $expectedHouseDigits)
        $houseFullMatch = [string]::IsNullOrWhiteSpace($expectedHouseNumber) -or ($candidate.HouseNumberFull -eq $expectedHouseNumber)

        $strictMatch = $streetMatches -and $postcodeMatches -and $cityMatches -and $houseFullMatch

        $reason = if ($strictMatch) {
            'exact'
        }
        elseif (-not $streetMatches) {
            'street_mismatch'
        }
        elseif (-not $postcodeMatches) {
            'postcode_mismatch'
        }
        elseif (-not $houseDigitsMatch) {
            'house_number_mismatch'
        }
        elseif (-not $houseFullMatch) {
            'house_suffix_mismatch'
        }
        elseif (-not $cityMatches) {
            'city_mismatch'
        }
        else {
            'fuzzy'
        }

        $ranking =
            ($(if ($strictMatch) { 1000 } else { 0 })) +
            ($(if ($streetMatches) { 200 } else { 0 })) +
            ($(if ($postcodeMatches) { 100 } else { 0 })) +
            ($(if ($cityMatches) { 50 } else { 0 })) +
            ($(if ($houseFullMatch) { 40 } elseif ($houseDigitsMatch) { 20 } else { 0 })) +
            [math]::Round($candidate.Score, 0)

        [pscustomobject]@{
            Candidate = $candidate
            StrictMatch = $strictMatch
            Reason = $reason
            Ranking = $ranking
        }
    }

    $strictCandidates = @($candidates | Where-Object { $_.StrictMatch })
    if ((Get-CollectionCount $strictCandidates) -gt 0) {
        return $strictCandidates | Sort-Object Ranking -Descending | Select-Object -First 1
    }

    return $candidates | Sort-Object Ranking -Descending | Select-Object -First 1
}

function Invoke-PdokGeocodingForRows {
    param(
        [object[]]$Rows,
        [int]$GeocodeDelayMs = 0,
        [int]$MaxConcurrency = 6,
        [scriptblock]$OnProgress
    )

    $preparedRecords = New-Object System.Collections.Generic.List[object]
    $progressCallback = $OnProgress

    foreach ($row in $Rows) {
        $record = [ordered]@{}
        foreach ($property in $row.PSObject.Properties) {
            $record[$property.Name] = $property.Value
        }

        $record['AddressQuery'] = Build-AddressQuery -Row ([pscustomobject]$record)
        $record['_PdokRequestUris'] = @(Build-PdokRequestUris -Row ([pscustomobject]$record))

        $hasFinalX = $null -ne (Convert-FlexibleNumberToDouble $record['FinalRdX'])
        $hasFinalY = $null -ne (Convert-FlexibleNumberToDouble $record['FinalRdY'])
        $record['_HasExistingCoordinates'] = ($hasFinalX -and $hasFinalY)

        $preparedRecords.Add($record)
    }

    $queryCache = @{}
    $queryTotal = 0
    $completedQueries = 0
    $candidateResultsByIndex = @{}
    $unresolvedIndexes = New-Object System.Collections.Generic.List[int]
    $maxStageCount = 0

    for ($recordIndex = 0; $recordIndex -lt $preparedRecords.Count; $recordIndex++) {
        $record = $preparedRecords[$recordIndex]
        if ([bool]$record['_HasExistingCoordinates']) {
            continue
        }

        $pdokRequestUris = @($record['_PdokRequestUris'])
        $requestUriCount = Get-CollectionCount $pdokRequestUris
        if ($requestUriCount -eq 0) {
            continue
        }

        $unresolvedIndexes.Add($recordIndex)
        if ($requestUriCount -gt $maxStageCount) {
            $maxStageCount = $requestUriCount
        }
    }

    for ($stageIndex = 0; $stageIndex -lt $maxStageCount -and (Get-CollectionCount $unresolvedIndexes) -gt 0; $stageIndex++) {
        $stageQueries = New-Object System.Collections.Generic.List[string]
        $stageSeen = @{}

        foreach ($recordIndex in @($unresolvedIndexes)) {
            $pdokRequestUris = @($preparedRecords[$recordIndex]['_PdokRequestUris'])
            if ($stageIndex -ge (Get-CollectionCount $pdokRequestUris)) {
                continue
            }

            $requestUri = [string]$pdokRequestUris[$stageIndex]
            if ([string]::IsNullOrWhiteSpace($requestUri)) {
                continue
            }

            if ($queryCache.ContainsKey($requestUri) -or $stageSeen.ContainsKey($requestUri)) {
                continue
            }

            $stageQueries.Add($requestUri)
            $stageSeen[$requestUri] = $true
        }

        $stageQueryArray = $stageQueries.ToArray()
        $stageQueryCount = Get-CollectionCount $stageQueryArray
        if ($stageQueryCount -gt 0) {
            $queryTotal += $stageQueryCount
            $completedBeforeStage = $completedQueries
            $stageCache = Invoke-PdokQueryBatch -Queries $stageQueryArray -MaxConcurrency $MaxConcurrency -DelayBetweenDispatchMs $GeocodeDelayMs -OnProgress {
                param($done, $total, $query)
                if ($progressCallback) {
                    & $progressCallback ($completedBeforeStage + $done) $queryTotal $query
                }
            }

            foreach ($entry in $stageCache.GetEnumerator()) {
                $queryCache[$entry.Key] = $entry.Value
            }

            $completedQueries += $stageQueryCount
        }

        $nextUnresolvedIndexes = New-Object System.Collections.Generic.List[int]
        foreach ($recordIndex in @($unresolvedIndexes)) {
            $record = $preparedRecords[$recordIndex]
            $pdokRequestUris = @($record['_PdokRequestUris'])
            if ($stageIndex -ge (Get-CollectionCount $pdokRequestUris)) {
                continue
            }

            $requestUri = [string]$pdokRequestUris[$stageIndex]
            if ([string]::IsNullOrWhiteSpace($requestUri)) {
                if (($stageIndex + 1) -lt (Get-CollectionCount $pdokRequestUris)) {
                    $nextUnresolvedIndexes.Add($recordIndex)
                }
                continue
            }

            $docs = @()
            if ($queryCache.ContainsKey($requestUri)) {
                $docs = @($queryCache[$requestUri])
            }

            $candidateResult = Select-PdokCandidateForRow -Row ([pscustomobject]$record) -Docs $docs
            if ($null -ne $candidateResult) {
                $candidateResultsByIndex[$recordIndex] = $candidateResult
                continue
            }

            if (($stageIndex + 1) -lt (Get-CollectionCount $pdokRequestUris)) {
                $nextUnresolvedIndexes.Add($recordIndex)
            }
        }

        $unresolvedIndexes = $nextUnresolvedIndexes
    }

    $resultRows = New-Object System.Collections.Generic.List[object]
    $exactCount = 0
    $tolerantCount = 0
    $notFoundCount = 0
    $notExactCount = 0
    $skippedCount = 0

    for ($preparedIndex = 0; $preparedIndex -lt $preparedRecords.Count; $preparedIndex++) {
        $record = $preparedRecords[$preparedIndex]
        $sourceFile = [string]$record['SourceFile']
        $sourcePath = [string]$record['SourcePath']
        $sourceType = [string]$record['SourceType']
        $addressQuery = [string]$record['AddressQuery']
        $pdokRequestUris = @($record['_PdokRequestUris'])
        $hasExistingCoordinates = [bool]$record['_HasExistingCoordinates']
        [void]$record.Remove('_HasExistingCoordinates')
        [void]$record.Remove('_PdokRequestUris')

        if ($hasExistingCoordinates) {
            $skippedCount += 1
            $resultRows.Add((New-PreparedRowObject -Row ([pscustomobject]$record) -SourceFile $sourceFile -SourcePath $sourcePath -SourceType $sourceType))
            continue
        }

        if ((Get-CollectionCount $pdokRequestUris) -eq 0) {
            if ([string]::IsNullOrWhiteSpace([string]$record['MatchStatus'])) {
                $record['MatchStatus'] = 'pdok_missing_address'
            }
            $skippedCount += 1
            $resultRows.Add((New-PreparedRowObject -Row ([pscustomobject]$record) -SourceFile $sourceFile -SourcePath $sourcePath -SourceType $sourceType))
            continue
        }

        $result = $null
        if ($candidateResultsByIndex.ContainsKey($preparedIndex)) {
            $result = $candidateResultsByIndex[$preparedIndex]
        }
        if ($null -eq $result) {
            $record['PdokDisplayName'] = $null
            $record['PdokType'] = $null
            $record['PdokScore'] = $null
            $record['PdokRdX'] = $null
            $record['PdokRdY'] = $null
            $record['PdokLon'] = $null
            $record['PdokLat'] = $null
            $record['PdokStrictMatch'] = 'False'
            $record['PdokMatchReason'] = 'not_found'
            $record['MatchStatus'] = 'pdok_not_found'
            $notFoundCount += 1
            $resultRows.Add((New-PreparedRowObject -Row ([pscustomobject]$record) -SourceFile $sourceFile -SourcePath $sourcePath -SourceType $sourceType))
            continue
        }

        $candidate = $result.Candidate
        $record['PdokDisplayName'] = $candidate.DisplayName
        $record['PdokType'] = $candidate.Type
        $record['PdokScore'] = $candidate.Score
        $record['PdokRdX'] = $candidate.RdX
        $record['PdokRdY'] = $candidate.RdY
        $record['PdokLon'] = $candidate.Lon
        $record['PdokLat'] = $candidate.Lat
        $record['PdokStrictMatch'] = if ($result.StrictMatch) { 'True' } else { 'False' }
        $record['PdokMatchReason'] = $result.Reason

        $acceptTolerantMatch = Test-IsPdokToleratedReason -Reason ([string]$result.Reason)
        $acceptFallbackMatch = (-not $result.StrictMatch -and -not $acceptTolerantMatch -and $null -ne $candidate.RdX -and $null -ne $candidate.RdY)
        if (($result.StrictMatch -or $acceptTolerantMatch -or $acceptFallbackMatch) -and $null -ne $candidate.RdX -and $null -ne $candidate.RdY) {
            $record['FinalRdX'] = $candidate.RdX
            $record['FinalRdY'] = $candidate.RdY
            if ($null -ne $candidate.Lon -and $null -ne $candidate.Lat) {
                $record['FinalLon'] = $candidate.Lon
                $record['FinalLat'] = $candidate.Lat
            }
            else {
                $wgs84 = Convert-RdToWgs84 -X ([double]$candidate.RdX) -Y ([double]$candidate.RdY)
                $record['FinalLon'] = [math]::Round([double]$wgs84.Longitude, 8)
                $record['FinalLat'] = [math]::Round([double]$wgs84.Latitude, 8)
            }
            if ($result.StrictMatch) {
                $record['CoordinateSource'] = 'pdok'
                $record['MatchStatus'] = 'pdok_exact'
                $exactCount += 1
            }
            else {
                $record['CoordinateSource'] = 'pdok_tolerant'
                $record['MatchStatus'] = 'pdok_tolerant_house_suffix'
                $tolerantCount += 1
            }
            if ($acceptFallbackMatch) {
                $record['CoordinateSource'] = 'pdok_fallback'
                $record['MatchStatus'] = 'pdok_fallback_non_exact'
                $notExactCount += 1
            }
        }
        else {
            $record['MatchStatus'] = 'pdok_not_exact'
            $notExactCount += 1
        }

        $resultRows.Add((New-PreparedRowObject -Row ([pscustomobject]$record) -SourceFile $sourceFile -SourcePath $sourcePath -SourceType $sourceType))
    }

    return [pscustomobject]@{
        Rows = $resultRows.ToArray()
        QueryCount = $queryTotal
        ExactCount = $exactCount
        TolerantCount = $tolerantCount
        NotFoundCount = $notFoundCount
        NotExactCount = $notExactCount
        SkippedCount = $skippedCount
    }
}

function Geocode-GridViaPdok {
    $rows = Convert-DataTableRowsToObjects -Table $script:Table
    if ((Get-CollectionCount $rows) -eq 0) {
        Show-InfoMessage 'Er staan geen rijen in de workbench.'
        return
    }

    $previousStatus = if ($script:StatusLabel) { $script:StatusLabel.Text } else { '' }
    $previousUseWaitCursor = $script:MainForm.UseWaitCursor
    $script:MainForm.UseWaitCursor = $true

    try {
        $result = Invoke-PdokGeocodingForRows -Rows $rows -GeocodeDelayMs $script:DefaultGeocodeDelayMs -MaxConcurrency $script:DefaultGeocodeConcurrency -OnProgress {
            param($done, $total, $query)
            if ($script:StatusLabel) {
                $script:StatusLabel.Text = "PDOK geocoderen: $done / $total"
            }
            [System.Windows.Forms.Application]::DoEvents()
        }

        Update-TableFromPreparedRows -Rows $result.Rows

        $summary = "PDOK geocoderen klaar.`n`nVerstuurde unieke queries: {0}`nExacte matches: {1}`nTolerant (huisnummer-suffix): {2}`nNiet exact: {3}`nNiet gevonden: {4}`nOvergeslagen: {5}" -f $result.QueryCount, $result.ExactCount, $result.TolerantCount, $result.NotExactCount, $result.NotFoundCount, $result.SkippedCount
        Show-InfoMessage $summary
    }
    catch {
        Show-ErrorMessage $_.Exception.Message
    }
    finally {
        $script:MainForm.UseWaitCursor = $previousUseWaitCursor
        if ($script:StatusLabel) {
            if ([string]::IsNullOrWhiteSpace($previousStatus)) {
                Update-StatusBar
            }
            else {
                Update-StatusBar
            }
        }
    }
}

function Invoke-EnexisWfsMatchingForRows {
    param(
        [object[]]$Rows,
        [scriptblock]$OnProgress
    )

    $preparedRecords = New-Object System.Collections.Generic.List[object]
    $needsServiceConnection = $false
    $needsStreetFurniture = $false
    $addressGroupCounts = @{}
    $addressGroupLastIndex = @{}
    $addressGroupHasNonBouwa = @{}
    $originalIndex = 0

    foreach ($row in $Rows) {
        $record = [ordered]@{}
        foreach ($property in $row.PSObject.Properties) {
            $record[$property.Name] = $property.Value
        }

        $record['_OriginalIndex'] = $originalIndex
        $usageCategory = Get-UsageCategory -Row ([pscustomobject]$record)
        $record['UsageCategory'] = $usageCategory
        $isBouwaansluiting = Test-IsBouwaansluitingUsage -Row ([pscustomobject]$record)
        $record['_IsBouwaansluiting'] = $isBouwaansluiting
        $addressGroupKey = Get-AddressGroupKey -Row ([pscustomobject]$record)
        if ([string]::IsNullOrWhiteSpace($addressGroupKey)) {
            $addressGroupKey = "__ROW__$originalIndex"
        }
        $record['_AddressGroupKey'] = $addressGroupKey

        if (-not $addressGroupCounts.ContainsKey($addressGroupKey)) {
            $addressGroupCounts[$addressGroupKey] = 0
        }
        $addressGroupCounts[$addressGroupKey] = [int]$addressGroupCounts[$addressGroupKey] + 1
        $addressGroupLastIndex[$addressGroupKey] = $originalIndex
        if (-not $isBouwaansluiting) {
            $addressGroupHasNonBouwa[$addressGroupKey] = $true
        }

        if ($usageCategory -eq 'street_furniture') {
            $needsStreetFurniture = $true
        }
        else {
            $needsServiceConnection = $true
        }

        $preparedRecords.Add($record)
        $originalIndex += 1
    }

    $recordsForMatching = @(
        $preparedRecords |
            Sort-Object `
                @{ Expression = {
                    $groupKey = [string]$_.Item('_AddressGroupKey')
                    $priority = [double]$_.Item('_OriginalIndex')
                    $isBouwa = [bool]$_.Item('_IsBouwaansluiting')
                    $sameAddressCount = [int]$addressGroupCounts[$groupKey]
                    $hasNonBouwa = $addressGroupHasNonBouwa.ContainsKey($groupKey) -and [bool]$addressGroupHasNonBouwa[$groupKey]
                    if ($isBouwa -and $sameAddressCount -gt 1 -and $hasNonBouwa) {
                        $priority = [double]$addressGroupLastIndex[$groupKey] + 0.001 + ([double]$_.Item('_OriginalIndex') / 1000000.0)
                    }

                    $priority
                }}, `
                @{ Expression = { [int]$_.Item('_OriginalIndex') } }
    )

    $bbox = New-BoundingBoxFromRows -Rows $Rows -BufferMeters $script:WfsBufferMeters
    if ($null -eq $bbox) {
        return [pscustomobject]@{
            Rows = $Rows
            ServiceFeatureCount = 0
            StreetFurnitureFeatureCount = 0
            ServiceMatchedCount = 0
            StreetFurnitureMatchedCount = 0
            UnmatchedCount = 0
            SkippedCount = (Get-CollectionCount $Rows)
        }
    }

    $serviceFeatures = @()
    $streetFurnitureFeatures = @()
    $serviceSpatialIndex = $null
    $streetFurnitureSpatialIndex = $null
    $serviceNearbyCache = @{}
    $streetNearbyCache = @{}
    $progressStep = 0
    $progressTotal = 0
    if ($needsServiceConnection) { $progressTotal += 1 }
    if ($needsStreetFurniture) { $progressTotal += 1 }
    if ($progressTotal -eq 0) { $progressTotal = 1 }

    if ($needsServiceConnection) {
        $progressStep += 1
        if ($OnProgress) {
            & $OnProgress $progressStep $progressTotal 'service_connection'
        }
        $serviceRaw = @(Get-WfsFeaturesFromService -BaseUrl $script:EnexisWfsUrl -LayerName $script:EnexisServiceConnectionLayer -BoundingBox $bbox)
        $serviceFeatures = @(Prepare-WfsFeatures -RawFeatures $serviceRaw -LayerCategory 'service_connection' -LayerName $script:EnexisServiceConnectionLayer)
        $serviceSpatialIndex = New-WfsSpatialIndex -Features $serviceFeatures -CellSize ([Math]::Max(10, $script:WfsSnapDistanceMeters))
    }

    if ($needsStreetFurniture) {
        $progressStep += 1
        if ($OnProgress) {
            & $OnProgress $progressStep $progressTotal 'street_furniture'
        }
        $streetRaw = @(Get-WfsFeaturesFromService -BaseUrl $script:EnexisWfsUrl -LayerName $script:EnexisStreetFurnitureLayer -BoundingBox $bbox)
        $streetFurnitureFeatures = @(Prepare-WfsFeatures -RawFeatures $streetRaw -LayerCategory 'street_furniture' -LayerName $script:EnexisStreetFurnitureLayer)
        $streetFurnitureSpatialIndex = New-WfsSpatialIndex -Features $streetFurnitureFeatures -CellSize ([Math]::Max(20, $script:WfsStreetFurnitureSnapDistanceMeters))
    }

    $resultRows = New-Object System.Collections.Generic.List[object]
    $serviceMatchedCount = 0
    $streetFurnitureMatchedCount = 0
    $unmatchedCount = 0
    $pointAlreadyUsedCount = 0
    $skippedCount = 0
    $usedFeatureIds = @{}
    $usedPointKeys = @{}
    $processedByIndex = @{}

    foreach ($record in $recordsForMatching) {
        $sourceFile = [string]$record['SourceFile']
        $sourcePath = [string]$record['SourcePath']
        $sourceType = [string]$record['SourceType']
        $originalIndex = [int]$record['_OriginalIndex']
        $seed = Get-SeedRdPoint -Row ([pscustomobject]$record)
        $usageCategory = [string]$record['UsageCategory']

        $record['WfsFeatureId'] = $null
        $record['WfsLayer'] = $null
        $record['WfsDescription'] = $null
        $record['WfsMatchMode'] = $null
        $record['WfsDistanceM'] = $null

        if ($null -eq $seed) {
            $skippedCount += 1
            if ([string]::IsNullOrWhiteSpace([string]$record['MatchStatus'])) {
                $record['MatchStatus'] = 'enexis_missing_seed'
            }
            $processedByIndex[$originalIndex] = (New-PreparedRowObject -Row ([pscustomobject]$record) -SourceFile $sourceFile -SourcePath $sourcePath -SourceType $sourceType)
            continue
        }

        $selection = $null
        if ($usageCategory -eq 'street_furniture') {
            if ((Get-CollectionCount $streetFurnitureFeatures) -gt 0) {
                $selection = Select-WfsStreetFurnitureFeatureForRow -Row ([pscustomobject]$record) -Features $streetFurnitureFeatures -SpatialIndex $streetFurnitureSpatialIndex -BaseX $seed.X -BaseY $seed.Y -MaxDistanceMeters $script:WfsStreetFurnitureSnapDistanceMeters -UsedFeatureIds $usedFeatureIds -UsedPointKeys $usedPointKeys -NearbyCache $streetNearbyCache
            }
        }
        else {
            if ((Get-CollectionCount $serviceFeatures) -gt 0) {
                $selection = Select-WfsServiceConnectionFeatureForRow -Row ([pscustomobject]$record) -Features $serviceFeatures -SpatialIndex $serviceSpatialIndex -BaseX $seed.X -BaseY $seed.Y -MaxDistanceMeters $script:WfsSnapDistanceMeters -UsedFeatureIds $usedFeatureIds -UsedPointKeys $usedPointKeys -NearbyCache $serviceNearbyCache
            }
        }

        if ($null -eq $selection -or $null -eq $selection.Feature) {
            $unmatchedCount += 1
            if ($null -ne $selection -and $selection.IsUniqueExhausted) {
                $pointAlreadyUsedCount += 1
            }
            if ($usageCategory -eq 'street_furniture') {
                $record['WfsLayer'] = 'street_furniture'
                if ($null -ne $selection -and $selection.IsUniqueExhausted) {
                    $record['WfsMatchMode'] = 'street_furniture_point_already_used'
                    $record['MatchStatus'] = 'street_furniture_point_already_used_keep_seed'
                }
                else {
                    $record['WfsMatchMode'] = 'street_furniture_no_match'
                    $record['MatchStatus'] = 'street_furniture_no_match_keep_seed'
                }
            }
            else {
                $record['WfsLayer'] = 'service_connection'
                if ($null -ne $selection -and $selection.IsUniqueExhausted) {
                    $record['WfsMatchMode'] = 'service_connection_point_already_used'
                    $record['MatchStatus'] = 'service_connection_point_already_used_keep_seed'
                }
                else {
                    $record['WfsMatchMode'] = 'service_connection_no_match'
                    $record['MatchStatus'] = 'service_connection_no_match_keep_seed'
                }
            }
            $processedByIndex[$originalIndex] = (New-PreparedRowObject -Row ([pscustomobject]$record) -SourceFile $sourceFile -SourcePath $sourcePath -SourceType $sourceType)
            continue
        }

        $feature = $selection.Feature
        $usedFeatureIds[[string]$feature.FeatureId] = $true
        $usedPointKeys[(Get-WfsFeaturePointKey -Feature $feature)] = $true
        $record['WfsFeatureId'] = $feature.FeatureId
        $record['WfsLayer'] = $feature.LayerCategory
        $record['WfsDescription'] = $feature.Description
        $record['WfsMatchMode'] = $selection.MatchMode
        $record['WfsDistanceM'] = [math]::Round([double]$selection.Distance, 2)
        $record['FinalRdX'] = $feature.RdX
        $record['FinalRdY'] = $feature.RdY

        $wgs84 = Convert-RdToWgs84 -X $feature.RdX -Y $feature.RdY
        $record['FinalLon'] = [math]::Round([double]$wgs84.Longitude, 8)
        $record['FinalLat'] = [math]::Round([double]$wgs84.Latitude, 8)
        $record['CoordinateSource'] = 'wfs'
        $record['MatchStatus'] = $selection.MatchMode

        if ($usageCategory -eq 'street_furniture') {
            $streetFurnitureMatchedCount += 1
        }
        else {
            $serviceMatchedCount += 1
        }

        $processedByIndex[$originalIndex] = (New-PreparedRowObject -Row ([pscustomobject]$record) -SourceFile $sourceFile -SourcePath $sourcePath -SourceType $sourceType)
    }

    foreach ($index in @($processedByIndex.Keys | Sort-Object)) {
        $resultRows.Add($processedByIndex[$index])
    }

    return [pscustomobject]@{
        Rows = $resultRows.ToArray()
        ServiceFeatureCount = (Get-CollectionCount $serviceFeatures)
        StreetFurnitureFeatureCount = (Get-CollectionCount $streetFurnitureFeatures)
        ServiceMatchedCount = $serviceMatchedCount
        StreetFurnitureMatchedCount = $streetFurnitureMatchedCount
        UnmatchedCount = $unmatchedCount
        PointAlreadyUsedCount = $pointAlreadyUsedCount
        SkippedCount = $skippedCount
    }
}

function Snap-GridToEnexisWfs {
    $rows = Convert-DataTableRowsToObjects -Table $script:Table
    if ((Get-CollectionCount $rows) -eq 0) {
        Show-InfoMessage 'Er staan geen rijen in de workbench.'
        return
    }

    $previousUseWaitCursor = $script:MainForm.UseWaitCursor
    $script:MainForm.UseWaitCursor = $true

    try {
        $result = Invoke-EnexisWfsMatchingForRows -Rows $rows -OnProgress {
            param($done, $total, $stage)
            if ($script:StatusLabel) {
                $script:StatusLabel.Text = "Enexis WFS laden: $done / $total ($stage)"
            }
            [System.Windows.Forms.Application]::DoEvents()
        }

        Update-TableFromPreparedRows -Rows $result.Rows

        $summary = "Enexis klaar.`n`nService connection features: {0}`nStreet furniture features: {1}`nService matches: {2}`nStreet furniture matches: {3}`nGeen Enexis-match: {4}`nPunt al gebruikt: {5}`nOvergeslagen: {6}" -f $result.ServiceFeatureCount, $result.StreetFurnitureFeatureCount, $result.ServiceMatchedCount, $result.StreetFurnitureMatchedCount, $result.UnmatchedCount, $result.PointAlreadyUsedCount, $result.SkippedCount
        Show-InfoMessage $summary
    }
    catch {
        Show-ErrorMessage $_.Exception.Message
    }
    finally {
        $script:MainForm.UseWaitCursor = $previousUseWaitCursor
        Update-StatusBar
    }
}

function Import-TextFile {
    param([string]$Path)

    $rows = Parse-LovionTextLines -Lines (Read-TextFileLines -Path $Path)
    $prepared = foreach ($row in $rows) {
        New-PreparedRowObject -Row $row -SourceFile ([System.IO.Path]::GetFileNameWithoutExtension($Path)) -SourcePath $Path -SourceType 'Text'
    }

    Add-RowsToTable -Rows $prepared
}

function Import-TextContentFromPaste {
    param(
        [string]$TextContent,
        [string]$SourceName
    )

    $rows = @(ConvertFrom-LovionClipboardContent -TextContent $TextContent)
    if ((Get-CollectionCount $rows) -eq 0) {
        throw 'Geen herkenbare Lovion-tekst of tabelrijen gevonden.'
    }
    $prepared = foreach ($row in $rows) {
        New-PreparedRowObject -Row $row -SourceFile $SourceName -SourcePath '' -SourceType 'Paste'
    }

    Add-RowsToTable -Rows $prepared
}

function Get-LovionMacroBytes {
    if (-not [string]::IsNullOrWhiteSpace([string]$script:EmbeddedLovionMacroXmlBase64)) {
        try {
            $embeddedBytes = [Convert]::FromBase64String([string]$script:EmbeddedLovionMacroXmlBase64)
            return ,([byte[]]$embeddedBytes)
        }
        catch {
            throw "De ingebouwde Lovion-macro kon niet worden gelezen: $($_.Exception.Message)"
        }
    }

    $macroPath = Join-Path -Path $script:ScriptDirectory -ChildPath $script:LovionMacroRelativePath
    if (-not (Test-Path -LiteralPath $macroPath -PathType Leaf)) {
        throw "Het Lovion-macrobestand ontbreekt: $macroPath"
    }
    return ,([System.IO.File]::ReadAllBytes($macroPath))
}

function Get-LovionMacroXml {
    [byte[]]$macroBytes = Get-LovionMacroBytes
    return [System.Text.Encoding]::UTF8.GetString($macroBytes)
}

function Export-LovionMacroXml {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $parsedXml = [xml](Get-LovionMacroXml)
    if ($null -eq $parsedXml.Reports) {
        throw 'Het Lovion-macrobestand heeft geen geldige Reports-root.'
    }
    [byte[]]$macroBytes = Get-LovionMacroBytes
    [System.IO.File]::WriteAllBytes($Path, $macroBytes)
    return $Path
}

function Show-LovionMacroDialog {
    try {
        [xml]$macro = Get-LovionMacroXml
        $report = $macro.Reports.Report
        $macroName = [string]$report.Localizations.Localization.externalName
        $minimumRelease = [string]$macro.Reports.LovionFileFormat.Version.minRelease
        if ([string]::IsNullOrWhiteSpace($macroName)) {
            $macroName = 'Trafo zoeker Macro'
        }
        if ([string]::IsNullOrWhiteSpace($minimumRelease)) {
            $minimumRelease = '7.2.1'
        }
    }
    catch {
        Show-ErrorMessage $_.Exception.Message
        return
    }

    $dialog = New-Object System.Windows.Forms.Form
    $dialog.Text = 'Lovion macro installeren'
    $dialog.StartPosition = 'CenterParent'
    $dialog.Size = New-Object System.Drawing.Size(780, 570)
    $dialog.MinimumSize = New-Object System.Drawing.Size(780, 570)
    $dialog.MaximizeBox = $false
    $dialog.MinimizeBox = $false
    $dialog.FormBorderStyle = 'FixedDialog'
    $dialog.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#f8f6f0')

    $infoLabel = New-Object System.Windows.Forms.Label
    $infoLabel.Text = "Lovion-macro: $macroName"
    $infoLabel.Location = New-Object System.Drawing.Point(16, 16)
    $infoLabel.Size = New-Object System.Drawing.Size(730, 28)
    $infoLabel.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 12)

    $details = New-Object System.Windows.Forms.RichTextBox
    $details.Location = New-Object System.Drawing.Point(16, 54)
    $details.Size = New-Object System.Drawing.Size(730, 414)
    $details.Anchor = 'Top,Bottom,Left,Right'
    $details.ReadOnly = $true
    $details.BackColor = [System.Drawing.Color]::White
    $details.BorderStyle = 'FixedSingle'
    $details.Font = New-Object System.Drawing.Font('Segoe UI', 10)
    $details.DetectUrls = $false
    $details.ScrollBars = 'Vertical'
    $details.Text = @"
Deze macro hoort in Lovion onder:
GEN > Elektriciteit > LS stroomtransformatorgroep

Installeren in Lovion/Citrix:
1. Klik hieronder op 'XML downloaden' en sla het bestand op.
2. Open in Lovion de functie 'Rapporten importeren'.
3. Selecteer het opgeslagen XML-bestand en importeer/installeer de macro.
4. Controleer daarna onder LS stroomtransformatorgroep of '$macroName' zichtbaar is.
5. Gebruik bij het uitvoeren de parameter 'Station' en vul het stationnummer in.

Compatibiliteit: Lovion release $minimumRelease of nieuwer.

De Coordinate Tool levert het juiste XML-bestand en de installatie-informatie.
De daadwerkelijke import wordt in de native Lovion/Citrix-app uitgevoerd.
"@

    $buttonPanel = New-Object System.Windows.Forms.FlowLayoutPanel
    $buttonPanel.Dock = 'Bottom'
    $buttonPanel.Height = 58
    $buttonPanel.FlowDirection = 'RightToLeft'
    $buttonPanel.Padding = New-Object System.Windows.Forms.Padding(8)

    $closeButton = New-Object System.Windows.Forms.Button
    $closeButton.Text = 'Sluiten'
    $closeButton.Width = 110
    $closeButton.Height = 32

    $downloadButton = New-Object System.Windows.Forms.Button
    $downloadButton.Text = 'XML downloaden'
    $downloadButton.Width = 155
    $downloadButton.Height = 32
    $downloadButton.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#184e77')
    $downloadButton.ForeColor = [System.Drawing.Color]::White
    $downloadButton.FlatStyle = 'Flat'

    $buttonPanel.Controls.AddRange(@($closeButton, $downloadButton))
    $dialog.Controls.AddRange(@($infoLabel, $details, $buttonPanel))

    $closeButton.Add_Click({
        $dialog.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
        $dialog.Close()
    })

    $downloadButton.Add_Click({
        try {
            $saveDialog = New-Object System.Windows.Forms.SaveFileDialog
            $saveDialog.Title = 'Lovion macro XML opslaan'
            $saveDialog.InitialDirectory = $script:CurrentDirectory
            $saveDialog.Filter = 'Lovion macro XML (*.xml)|*.xml|Alle bestanden|*.*'
            $saveDialog.FileName = 'Trafo zoeken macro rapport.xml'
            if ($saveDialog.ShowDialog($dialog) -eq [System.Windows.Forms.DialogResult]::OK) {
                Export-LovionMacroXml -Path $saveDialog.FileName | Out-Null
                Show-InfoMessage "Lovion-macro opgeslagen:`n$($saveDialog.FileName)`n`nImporteer dit bestand daarna in Lovion via 'Rapporten importeren'."
            }
            $saveDialog.Dispose()
        }
        catch {
            Show-ErrorMessage $_.Exception.Message
        }
    })

    $dialog.AcceptButton = $downloadButton
    $dialog.CancelButton = $closeButton
    [void]$dialog.ShowDialog($script:MainForm)
}

function Show-SourceNameDialog {
    param(
        [string]$DefaultName,
        [string]$Title = 'SourceFile Naam'
    )

    $dialog = New-Object System.Windows.Forms.Form
    $dialog.Text = $Title
    $dialog.StartPosition = 'CenterParent'
    $dialog.Size = New-Object System.Drawing.Size(520, 180)
    $dialog.MinimumSize = New-Object System.Drawing.Size(520, 180)
    $dialog.MaximizeBox = $false
    $dialog.MinimizeBox = $false
    $dialog.FormBorderStyle = 'FixedDialog'
    $dialog.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#f8f6f0')

    $label = New-Object System.Windows.Forms.Label
    $label.Text = 'Geef een naam voor SourceFile:'
    $label.Location = New-Object System.Drawing.Point(16, 18)
    $label.AutoSize = $true

    $textBox = New-Object System.Windows.Forms.TextBox
    $textBox.Location = New-Object System.Drawing.Point(18, 48)
    $textBox.Width = 470
    $textBox.Text = $DefaultName

    $buttonPanel = New-Object System.Windows.Forms.FlowLayoutPanel
    $buttonPanel.Dock = 'Bottom'
    $buttonPanel.Height = 52
    $buttonPanel.FlowDirection = 'RightToLeft'
    $buttonPanel.Padding = New-Object System.Windows.Forms.Padding(8)

    $okButton = New-Object System.Windows.Forms.Button
    $okButton.Text = 'OK'
    $okButton.Width = 110
    $okButton.Height = 30
    $okButton.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#184e77')
    $okButton.ForeColor = [System.Drawing.Color]::White
    $okButton.FlatStyle = 'Flat'

    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = 'Annuleren'
    $cancelButton.Width = 110
    $cancelButton.Height = 30

    $buttonPanel.Controls.AddRange(@($okButton, $cancelButton))
    $dialog.Controls.AddRange(@($label, $textBox, $buttonPanel))

    $okButton.Add_Click({
        $dialog.Tag = $textBox.Text
        $dialog.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $dialog.Close()
    })

    $cancelButton.Add_Click({
        $dialog.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
        $dialog.Close()
    })

    $dialog.AcceptButton = $okButton
    $dialog.CancelButton = $cancelButton
    [void]$dialog.ShowDialog($script:MainForm)

    if ($dialog.DialogResult -ne [System.Windows.Forms.DialogResult]::OK) {
        return $null
    }

    return [string]$dialog.Tag
}

function ConvertTo-StationNumberList {
    param([string]$Text)

    $stations = New-Object System.Collections.Generic.List[string]
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($part in @($Text -split '[,;\t\r\n]+')) {
        $station = ([string]$part).Trim()
        if (-not [string]::IsNullOrWhiteSpace($station) -and $seen.Add($station)) {
            $stations.Add($station)
        }
    }
    return $stations.ToArray()
}

function Show-StationNumbersDialog {
    $dialog = New-Object System.Windows.Forms.Form
    $dialog.Text = 'Station nummers'
    $dialog.StartPosition = 'CenterParent'
    $dialog.Size = New-Object System.Drawing.Size(580, 430)
    $dialog.MinimumSize = New-Object System.Drawing.Size(580, 430)
    $dialog.MaximizeBox = $false
    $dialog.MinimizeBox = $false
    $dialog.FormBorderStyle = 'FixedDialog'
    $dialog.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#f8f6f0')

    $label = New-Object System.Windows.Forms.Label
    $label.Text = "Plak of typ de stationnummers. Gebruik een nieuwe regel, komma of puntkomma tussen stations."
    $label.Location = New-Object System.Drawing.Point(16, 16)
    $label.Size = New-Object System.Drawing.Size(540, 38)

    $textBox = New-Object System.Windows.Forms.TextBox
    $textBox.Location = New-Object System.Drawing.Point(18, 58)
    $textBox.Size = New-Object System.Drawing.Size(540, 285)
    $textBox.Multiline = $true
    $textBox.AcceptsReturn = $true
    $textBox.AcceptsTab = $false
    $textBox.ScrollBars = 'Both'
    $textBox.WordWrap = $false

    $buttonPanel = New-Object System.Windows.Forms.FlowLayoutPanel
    $buttonPanel.Dock = 'Bottom'
    $buttonPanel.Height = 52
    $buttonPanel.FlowDirection = 'RightToLeft'
    $buttonPanel.Padding = New-Object System.Windows.Forms.Padding(8)

    $okButton = New-Object System.Windows.Forms.Button
    $okButton.Text = 'Start'
    $okButton.Width = 110
    $okButton.Height = 30
    $okButton.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#bc6c25')
    $okButton.ForeColor = [System.Drawing.Color]::White
    $okButton.FlatStyle = 'Flat'

    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = 'Annuleren'
    $cancelButton.Width = 110
    $cancelButton.Height = 30

    $buttonPanel.Controls.AddRange(@($okButton, $cancelButton))
    $dialog.Controls.AddRange(@($label, $textBox, $buttonPanel))

    $okButton.Add_Click({
        $stations = @(ConvertTo-StationNumberList -Text $textBox.Text)
        if ($stations.Count -eq 0) {
            [void][System.Windows.Forms.MessageBox]::Show($dialog, 'Vul minimaal een stationnummer in.', 'Station nummers', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)
            return
        }
        $dialog.Tag = $stations
        $dialog.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $dialog.Close()
    })

    $cancelButton.Add_Click({
        $dialog.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
        $dialog.Close()
    })

    $dialog.CancelButton = $cancelButton
    $dialog.Add_Shown({ $textBox.Focus() })
    [void]$dialog.ShowDialog($script:MainForm)
    if ($dialog.DialogResult -ne [System.Windows.Forms.DialogResult]::OK) {
        return $null
    }
    return @($dialog.Tag)
}

function Import-ClipboardText {
    try {
        $text = [System.Windows.Forms.Clipboard]::GetText()
    }
    catch {
        Show-ErrorMessage $_.Exception.Message
        return
    }

    if ([string]::IsNullOrWhiteSpace($text)) {
        Show-InfoMessage 'Het klembord bevat geen tekst.'
        return
    }

    try {
        $defaultName = 'Clipboard_{0}' -f (Get-Date -Format 'yyyyMMdd_HHmmss')
        $sourceName = Show-SourceNameDialog -DefaultName $defaultName -Title 'Klembord Import'
        if ($null -eq $sourceName) {
            return
        }
        if ([string]::IsNullOrWhiteSpace($sourceName)) {
            $sourceName = $defaultName
        }
        Import-TextContentFromPaste -TextContent $text -SourceName $sourceName
    }
    catch {
        Show-ErrorMessage $_.Exception.Message
    }
}

function Import-ExcelFile {
    param([string]$Path)

    $sheetName = Get-PreferredWorksheetName -Path $Path
    $rows = Read-ExcelRows -Path $Path -SheetName $sheetName
    $prepared = foreach ($row in $rows) {
        New-PreparedRowObject -Row $row -SourceFile ([System.IO.Path]::GetFileNameWithoutExtension($Path)) -SourcePath $Path -SourceType 'Excel'
    }

    Add-RowsToTable -Rows $prepared
}

function Import-CsvFile {
    param([string]$Path)

    $csvRows = Import-Csv -Path $Path
    $prepared = foreach ($row in $csvRows) {
        New-PreparedRowObject -Row $row -SourceFile ([System.IO.Path]::GetFileNameWithoutExtension($Path)) -SourcePath $Path -SourceType 'CSV'
    }

    Add-RowsToTable -Rows $prepared
}

function Import-FilesIntoGrid {
    param([string[]]$Paths)

    foreach ($path in $Paths) {
        try {
            $extension = [System.IO.Path]::GetExtension($path).ToLowerInvariant()
            switch ($extension) {
                '.txt' { Import-TextFile -Path $path }
                '.xlsx' { Import-ExcelFile -Path $path }
                '.csv' { Import-CsvFile -Path $path }
                default { Show-InfoMessage "Bestandstype niet ondersteund: $path" }
            }
            $script:CurrentDirectory = [System.IO.Path]::GetDirectoryName($path)
        }
        catch {
            Show-ErrorMessage ("Import mislukt voor '{0}`n`n{1}" -f $path, $_.Exception.Message)
        }
    }
}

function Format-DbfTextValue {
    param(
        [string]$Value,
        [int]$Length,
        [System.Text.Encoding]$Encoding
    )

    $text = if ($null -eq $Value) { '' } else { [string]$Value }
    while ($Encoding.GetByteCount($text) -gt $Length -and $text.Length -gt 0) {
        $text = $text.Substring(0, $text.Length - 1)
    }

    return $text.PadRight($Length)
}

function Format-DbfNumberValue {
    param(
        $Value,
        [int]$Length,
        [int]$Decimals
    )

    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) {
        return ''.PadLeft($Length)
    }

    $number = Convert-FlexibleNumberToDouble $Value
    if ($null -eq $number) {
        return ''.PadLeft($Length)
    }

    $format = if ($Decimals -gt 0) { 'F' + $Decimals } else { 'F0' }
    $text = $number.ToString($format, [System.Globalization.CultureInfo]::InvariantCulture)
    if ($text.Length -gt $Length) {
        $text = $text.Substring(0, $Length)
    }

    return $text.PadLeft($Length)
}

function Write-BigEndianInt32 {
    param(
        [System.IO.BinaryWriter]$Writer,
        [int]$Value
    )

    $bytes = [System.BitConverter]::GetBytes([int]$Value)
    [array]::Reverse($bytes)
    $Writer.Write($bytes)
}

function Write-ShapefileHeader {
    param(
        [System.IO.BinaryWriter]$Writer,
        [int]$FileLengthWords,
        [int]$ShapeType,
        [double]$MinX,
        [double]$MinY,
        [double]$MaxX,
        [double]$MaxY
    )

    Write-BigEndianInt32 -Writer $Writer -Value 9994
    for ($index = 0; $index -lt 5; $index++) {
        Write-BigEndianInt32 -Writer $Writer -Value 0
    }
    Write-BigEndianInt32 -Writer $Writer -Value $FileLengthWords
    $Writer.Write([int]1000)
    $Writer.Write([int]$ShapeType)
    $Writer.Write([double]$MinX)
    $Writer.Write([double]$MinY)
    $Writer.Write([double]$MaxX)
    $Writer.Write([double]$MaxY)
    $Writer.Write([double]0)
    $Writer.Write([double]0)
    $Writer.Write([double]0)
    $Writer.Write([double]0)
}

function Get-DbfSafeFieldName {
    param(
        [string]$Name,
        [hashtable]$UsedNames
    )

    $normalized = Normalize-Text $Name
    $ascii = [regex]::Replace($normalized, '[^A-Z0-9]+', '_').Trim('_')
    if ([string]::IsNullOrWhiteSpace($ascii)) {
        $ascii = 'FIELD'
    }
    if ($ascii.Length -gt 10) {
        $ascii = $ascii.Substring(0, 10)
    }
    if ($ascii -match '^\d') {
        $ascii = 'F' + $ascii.Substring(0, [Math]::Min(9, $ascii.Length))
    }

    $candidate = $ascii
    $suffix = 1
    while ($UsedNames.ContainsKey($candidate)) {
        $suffixText = [string]$suffix
        $prefixLength = [Math]::Min(10 - $suffixText.Length, $ascii.Length)
        $candidate = $ascii.Substring(0, $prefixLength) + $suffixText
        $suffix += 1
    }

    $UsedNames[$candidate] = $true
    return $candidate
}

function New-DynamicDbfFieldDefinitions {
    param([object[]]$Rows)

    $propertyNames = New-Object System.Collections.Generic.List[string]
    foreach ($row in $Rows) {
        foreach ($property in $row.PSObject.Properties) {
            if ($property.Name -like '_*') {
                continue
            }

            if (-not $propertyNames.Contains($property.Name)) {
                $propertyNames.Add($property.Name)
            }
        }
    }

    $numericFields = @(
        'OverdrachtspuntRdX1',
        'OverdrachtspuntRdY1',
        'OverdrachtspuntRdX2',
        'OverdrachtspuntRdY2',
        'PdokScore',
        'PdokRdX',
        'PdokRdY',
        'PdokLon',
        'PdokLat',
        'WfsDistanceM',
        'FinalRdX',
        'FinalRdY',
        'FinalLon',
        'FinalLat'
    )

    $usedNames = @{}
    $fields = New-Object System.Collections.Generic.List[object]
    foreach ($propertyName in $propertyNames) {
        $isNumeric = $numericFields -contains $propertyName
        if ($isNumeric) {
            $length = 18
            $decimals = if ($propertyName -in @('FinalLon', 'FinalLat')) { 8 } else { 3 }
            $type = 'N'
        }
        else {
            $length = 1
            foreach ($row in $Rows) {
                $value = Get-ObjectPropertyValue -Object $row -Name $propertyName
                $length = [Math]::Max($length, [Math]::Min(254, ([string]$value).Length))
            }
            $decimals = 0
            $type = 'C'
        }

        $fields.Add([pscustomobject]@{
            Name = Get-DbfSafeFieldName -Name $propertyName -UsedNames $usedNames
            OriginalName = $propertyName
            Type = $type
            Length = $length
            Decimals = $decimals
        })
    }

    return $fields
}

function Write-DbfFileDynamic {
    param(
        [object[]]$Rows,
        [object[]]$Fields,
        [string]$Path
    )

    $recordLength = 1
    foreach ($field in $Fields) {
        $recordLength += [int]$field.Length
    }

    $headerLength = 32 + ($Fields.Count * 32) + 1
    $encoding = [System.Text.Encoding]::GetEncoding(1252)
    $stream = $null
    $writer = $null

    try {
        $stream = [System.IO.File]::Create($Path)
        $writer = New-Object System.IO.BinaryWriter($stream, $encoding)

        $now = Get-Date
        $writer.Write([byte]0x03)
        $writer.Write([byte]($now.Year - 1900))
        $writer.Write([byte]$now.Month)
        $writer.Write([byte]$now.Day)
        $writer.Write([int]$Rows.Count)
        $writer.Write([int16]$headerLength)
        $writer.Write([int16]$recordLength)
        $writer.Write([byte[]](0..17 | ForEach-Object { [byte]0 }))
        $writer.Write([byte]125)
        $writer.Write([byte]0)

        foreach ($field in $Fields) {
            $nameBytes = $encoding.GetBytes($field.Name)
            $fieldName = New-Object byte[] 11
            [array]::Copy($nameBytes, 0, $fieldName, 0, [math]::Min($nameBytes.Length, 10))
            $writer.Write($fieldName)
            $writer.Write([byte][char]$field.Type)
            $writer.Write([int]0)
            $writer.Write([byte]$field.Length)
            $writer.Write([byte]$field.Decimals)
            $writer.Write([byte[]](0..13 | ForEach-Object { [byte]0 }))
        }

        $writer.Write([byte]0x0D)

        foreach ($row in $Rows) {
            $writer.Write([byte]0x20)
            foreach ($field in $Fields) {
                $value = Get-ObjectPropertyValue -Object $row -Name $field.OriginalName
                $formatted = if ($field.Type -eq 'N') {
                    Format-DbfNumberValue -Value $value -Length $field.Length -Decimals $field.Decimals
                }
                else {
                    Format-DbfTextValue -Value ([string]$value) -Length $field.Length -Encoding $encoding
                }

                $writer.Write($encoding.GetBytes($formatted))
            }
        }

        $writer.Write([byte]0x1A)
    }
    finally {
        if ($writer) { $writer.Close() } elseif ($stream) { $stream.Close() }
    }
}

function Export-GeoJson {
    param(
        [object[]]$Rows,
        [string]$Path
    )

    $features = New-Object System.Collections.Generic.List[object]
    foreach ($row in $Rows) {
        $x = Convert-FlexibleNumberToDouble (Get-ObjectPropertyValue -Object $row -Name 'FinalRdX')
        $y = Convert-FlexibleNumberToDouble (Get-ObjectPropertyValue -Object $row -Name 'FinalRdY')
        if ($null -eq $x -or $null -eq $y) {
            continue
        }

        $properties = [ordered]@{}
        foreach ($property in $row.PSObject.Properties) {
            if ($property.Name -in @('FinalRdX', 'FinalRdY')) {
                continue
            }

            $properties[$property.Name] = $property.Value
        }

        $features.Add([ordered]@{
            type = 'Feature'
            geometry = [ordered]@{
                type = 'Point'
                coordinates = @($x, $y)
            }
            properties = $properties
        })
    }

    $geoJson = [ordered]@{
        type = 'FeatureCollection'
        name = 'lovion_gui_export'
        crs = [ordered]@{
            type = 'name'
            properties = [ordered]@{
                name = 'EPSG:28992'
            }
        }
        features = $features
    }

    $geoJson | ConvertTo-Json -Depth 8 | Set-Content -Path $Path -Encoding UTF8
}

function Export-PointShapefileDynamic {
    param(
        [object[]]$Rows,
        [string]$TargetShpPath
    )

    $pointRows = New-Object System.Collections.Generic.List[object]
    $points = New-Object System.Collections.Generic.List[object]
    foreach ($row in $Rows) {
        $point = Get-ExportPointForRow -Row $row
        if ($null -eq $point) {
            continue
        }

        $prepared = New-PreparedRowObject -Row $row -SourceFile ([string](Get-ObjectPropertyValue -Object $row -Name 'SourceFile')) -SourcePath ([string](Get-ObjectPropertyValue -Object $row -Name 'SourcePath')) -SourceType ([string](Get-ObjectPropertyValue -Object $row -Name 'SourceType'))
        $pointRows.Add($prepared)
        $points.Add($point)
    }

    if ($pointRows.Count -eq 0) {
        throw 'Er zijn geen rijen met coordinaten om als shapefile weg te schrijven.'
    }

    $targetDirectory = [System.IO.Path]::GetDirectoryName($TargetShpPath)
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($TargetShpPath)
    if (-not (Test-Path -Path $targetDirectory)) {
        New-Item -Path $targetDirectory -ItemType Directory | Out-Null
    }

    $shpPath = Join-Path -Path $targetDirectory -ChildPath ($baseName + '.shp')
    $shxPath = Join-Path -Path $targetDirectory -ChildPath ($baseName + '.shx')
    $dbfPath = Join-Path -Path $targetDirectory -ChildPath ($baseName + '.dbf')
    $prjPath = Join-Path -Path $targetDirectory -ChildPath ($baseName + '.prj')
    $cpgPath = Join-Path -Path $targetDirectory -ChildPath ($baseName + '.cpg')
    $fieldMapPath = Join-Path -Path $targetDirectory -ChildPath ($baseName + '_fieldmap.csv')

    $xValues = @($points | ForEach-Object { [double]$_.X })
    $yValues = @($points | ForEach-Object { [double]$_.Y })

    $minX = ($xValues | Measure-Object -Minimum).Minimum
    $maxX = ($xValues | Measure-Object -Maximum).Maximum
    $minY = ($yValues | Measure-Object -Minimum).Minimum
    $maxY = ($yValues | Measure-Object -Maximum).Maximum

    $shpFileLengthWords = 50 + ($pointRows.Count * 14)
    $shxFileLengthWords = 50 + ($pointRows.Count * 4)

    $shpStream = $null
    $shxStream = $null
    $shpWriter = $null
    $shxWriter = $null

    try {
        $shpStream = [System.IO.File]::Create($shpPath)
        $shxStream = [System.IO.File]::Create($shxPath)
        $shpWriter = New-Object System.IO.BinaryWriter($shpStream)
        $shxWriter = New-Object System.IO.BinaryWriter($shxStream)

        Write-ShapefileHeader -Writer $shpWriter -FileLengthWords $shpFileLengthWords -ShapeType 1 -MinX $minX -MinY $minY -MaxX $maxX -MaxY $maxY
        Write-ShapefileHeader -Writer $shxWriter -FileLengthWords $shxFileLengthWords -ShapeType 1 -MinX $minX -MinY $minY -MaxX $maxX -MaxY $maxY

        $offsetWords = 50
        $recordNumber = 1
        for ($index = 0; $index -lt $pointRows.Count; $index++) {
            $row = $pointRows[$index]
            $point = $points[$index]
            $x = [double]$point.X
            $y = [double]$point.Y

            Write-BigEndianInt32 -Writer $shxWriter -Value $offsetWords
            Write-BigEndianInt32 -Writer $shxWriter -Value 10

            Write-BigEndianInt32 -Writer $shpWriter -Value $recordNumber
            Write-BigEndianInt32 -Writer $shpWriter -Value 10
            $shpWriter.Write([int]1)
            $shpWriter.Write([double]$x)
            $shpWriter.Write([double]$y)

            $offsetWords += 14
            $recordNumber += 1
        }
    }
    finally {
        if ($shpWriter) { $shpWriter.Close() } elseif ($shpStream) { $shpStream.Close() }
        if ($shxWriter) { $shxWriter.Close() } elseif ($shxStream) { $shxStream.Close() }
    }

    $fields = New-DynamicDbfFieldDefinitions -Rows $pointRows
    Write-DbfFileDynamic -Rows $pointRows -Fields $fields -Path $dbfPath
    $fields | Select-Object Name, OriginalName, Type, Length, Decimals | Export-Csv -Path $fieldMapPath -NoTypeInformation -Encoding UTF8
    Set-Content -Path $cpgPath -Value '1252' -Encoding ASCII
    Set-Content -Path $prjPath -Encoding ASCII -Value 'PROJCS["Amersfoort / RD New",GEOGCS["Amersfoort",DATUM["Amersfoort",SPHEROID["Bessel 1841",6377397.155,299.1528128]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Oblique_Stereographic"],PARAMETER["latitude_of_origin",52.15616055555555],PARAMETER["central_meridian",5.38763888888889],PARAMETER["scale_factor",0.9999079],PARAMETER["false_easting",155000],PARAMETER["false_northing",463000],UNIT["metre",1]]'

    return $fieldMapPath
}

function Export-GridToCsv {
    param([string]$Path)

    $rows = Convert-DataTableRowsToObjects -Table $script:Table
    $rows | Export-Csv -Path $Path -NoTypeInformation -Encoding UTF8
}

function Refresh-CoordinatesFromGrid {
    $rows = Convert-DataTableRowsToObjects -Table $script:Table
    Update-TableFromPreparedRows -Rows $rows
    Show-InfoMessage 'Coordinaten en afgeleide velden zijn opnieuw opgebouwd op basis van de huidige grid.'
}

function Refresh-UsageCategoriesFromGrid {
    $rows = Convert-DataTableRowsToObjects -Table $script:Table
    Update-TableFromPreparedRows -Rows $rows
}

function Show-StreetFurnitureTermsDialog {
    Ensure-StreetFurnitureTermsLoaded

    $dialog = New-Object System.Windows.Forms.Form
    $dialog.Text = 'Street Furniture Termen'
    $dialog.StartPosition = 'CenterParent'
    $dialog.Size = New-Object System.Drawing.Size(680, 620)
    $dialog.MinimumSize = New-Object System.Drawing.Size(560, 460)
    $dialog.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#f8f6f0')

    $infoLabel = New-Object System.Windows.Forms.Label
    $infoLabel.Text = 'Voeg termen toe, één per regel. Matching is niet hoofdlettergevoelig en mag overal in Gebruiksdoel voorkomen.'
    $infoLabel.Location = New-Object System.Drawing.Point(16, 16)
    $infoLabel.Size = New-Object System.Drawing.Size(630, 34)

    $pathLabel = New-Object System.Windows.Forms.Label
    $pathLabel.Text = "Config: $($script:StreetFurnitureTermsConfigPath)"
    $pathLabel.Location = New-Object System.Drawing.Point(16, 52)
    $pathLabel.Size = New-Object System.Drawing.Size(630, 18)
    $pathLabel.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#5c6770')

    $textBox = New-Object System.Windows.Forms.RichTextBox
    $textBox.Location = New-Object System.Drawing.Point(16, 82)
    $textBox.Size = New-Object System.Drawing.Size(632, 446)
    $textBox.Font = New-Object System.Drawing.Font('Consolas', 10)
    $textBox.WordWrap = $false
    $textBox.AcceptsTab = $true
    $textBox.DetectUrls = $false
    $textBox.Text = (($script:StreetFurnitureTerms | Sort-Object) -join [Environment]::NewLine)

    $buttonPanel = New-Object System.Windows.Forms.FlowLayoutPanel
    $buttonPanel.Dock = 'Bottom'
    $buttonPanel.Height = 56
    $buttonPanel.FlowDirection = 'RightToLeft'
    $buttonPanel.Padding = New-Object System.Windows.Forms.Padding(8)

    $saveButton = New-Object System.Windows.Forms.Button
    $saveButton.Text = 'Opslaan'
    $saveButton.Width = 120
    $saveButton.Height = 32
    $saveButton.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#184e77')
    $saveButton.ForeColor = [System.Drawing.Color]::White
    $saveButton.FlatStyle = 'Flat'

    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = 'Annuleren'
    $cancelButton.Width = 120
    $cancelButton.Height = 32

    $resetButton = New-Object System.Windows.Forms.Button
    $resetButton.Text = 'Standaard'
    $resetButton.Width = 120
    $resetButton.Height = 32

    $buttonPanel.Controls.AddRange(@($saveButton, $cancelButton, $resetButton))
    $dialog.Controls.AddRange(@($infoLabel, $pathLabel, $textBox, $buttonPanel))

    $resetButton.Add_Click({
        $textBox.Text = (($script:DefaultStreetFurnitureTerms | Sort-Object) -join [Environment]::NewLine)
    })

    $cancelButton.Add_Click({
        $dialog.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
        $dialog.Close()
    })

    $saveButton.Add_Click({
        try {
            $terms = Save-StreetFurnitureTerms -Terms $textBox.Lines
            Refresh-UsageCategoriesFromGrid
            Show-InfoMessage ("{0} street-furniture termen opgeslagen.`n`nUsageCategory is vernieuwd voor de huidige grid.`nKlik daarna opnieuw op 'Snap Enexis' als je bestaande Enexis-matches wilt actualiseren." -f $terms.Count)
            $dialog.DialogResult = [System.Windows.Forms.DialogResult]::OK
            $dialog.Close()
        }
        catch {
            Show-ErrorMessage $_.Exception.Message
        }
    })

    [void]$dialog.ShowDialog($script:MainForm)
}

function Show-PasteDialog {
    $dialog = New-Object System.Windows.Forms.Form
    $dialog.Text = 'Tekst Plakken'
    $dialog.StartPosition = 'CenterParent'
    $dialog.Size = New-Object System.Drawing.Size(900, 700)
    $dialog.MinimumSize = New-Object System.Drawing.Size(700, 500)
    $dialog.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#f8f6f0')

    $textBox = New-Object System.Windows.Forms.RichTextBox
    $textBox.Multiline = $true
    $textBox.ScrollBars = 'Both'
    $textBox.AcceptsTab = $true
    $textBox.WordWrap = $false
    $textBox.Font = New-Object System.Drawing.Font('Consolas', 10)
    $textBox.Dock = 'Fill'
    $textBox.DetectUrls = $false
    $textBox.HideSelection = $false
    $textBox.MaxLength = [int]::MaxValue

    $buttonPanel = New-Object System.Windows.Forms.FlowLayoutPanel
    $buttonPanel.Dock = 'Bottom'
    $buttonPanel.Height = 54
    $buttonPanel.FlowDirection = 'RightToLeft'
    $buttonPanel.Padding = New-Object System.Windows.Forms.Padding(8)

    $importButton = New-Object System.Windows.Forms.Button
    $importButton.Text = 'Toevoegen'
    $importButton.Width = 120
    $importButton.Height = 32
    $importButton.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#184e77')
    $importButton.ForeColor = [System.Drawing.Color]::White
    $importButton.FlatStyle = 'Flat'

    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = 'Annuleren'
    $cancelButton.Width = 120
    $cancelButton.Height = 32

    $clipboardButton = New-Object System.Windows.Forms.Button
    $clipboardButton.Text = 'Haal Uit Klembord'
    $clipboardButton.Width = 180
    $clipboardButton.Height = 32

    $buttonPanel.Controls.AddRange(@($importButton, $cancelButton, $clipboardButton))
    $dialog.Controls.Add($textBox)
    $dialog.Controls.Add($buttonPanel)

    $clipboardButton.Add_Click({
        try {
            $textBox.Text = [System.Windows.Forms.Clipboard]::GetText()
            $textBox.SelectionStart = $textBox.TextLength
            $textBox.SelectionLength = 0
        }
        catch {
            Show-ErrorMessage $_.Exception.Message
        }
    })

    $cancelButton.Add_Click({
        $dialog.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
        $dialog.Close()
    })

    $importButton.Add_Click({
        if ([string]::IsNullOrWhiteSpace($textBox.Text)) {
            Show-InfoMessage 'Er staat geen tekst in het plakvenster.'
            return
        }

        try {
            $defaultName = 'Plaksel_{0}' -f (Get-Date -Format 'yyyyMMdd_HHmmss')
            $sourceName = Show-SourceNameDialog -DefaultName $defaultName -Title 'Plakvenster Import'
            if ($null -eq $sourceName) {
                return
            }
            if ([string]::IsNullOrWhiteSpace($sourceName)) {
                $sourceName = $defaultName
            }
            Import-TextContentFromPaste -TextContent $textBox.Text -SourceName $sourceName
            $dialog.DialogResult = [System.Windows.Forms.DialogResult]::OK
            $dialog.Close()
        }
        catch {
            Show-ErrorMessage $_.Exception.Message
        }
    })

    [void]$dialog.ShowDialog($script:MainForm)
}

function Remove-SelectedRows {
    if (-not $script:Grid.SelectedRows.Count) {
        Show-InfoMessage 'Selecteer eerst een of meer rijen.'
        return
    }

    foreach ($selectedRow in @($script:Grid.SelectedRows)) {
        if (-not $selectedRow.IsNewRow) {
            $script:Grid.Rows.Remove($selectedRow)
        }
    }

    Update-StatusBar
}

function Clear-AllRows {
    if ($script:Table.Rows.Count -eq 0) {
        return
    }

    $result = [System.Windows.Forms.MessageBox]::Show($script:MainForm, 'Alle rijen verwijderen?', $script:AppName, [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Question)
    if ($result -eq [System.Windows.Forms.DialogResult]::Yes) {
        $script:Table.Rows.Clear()
        Update-StatusBar
    }
}

function Set-LovionBatchStatus {
    param([string]$Message)

    if ($script:StatusLabel) {
        $script:StatusLabel.Text = $Message
    }
    [System.Windows.Forms.Application]::DoEvents()
}

function Write-LovionBatchLog {
    param([string]$Message)

    try {
        $line = '{0} | {1}{2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff'), $Message, [Environment]::NewLine
        [System.IO.File]::AppendAllText($script:LovionBatchLogPath, $line, (New-Object System.Text.UTF8Encoding($false)))
    }
    catch {}
}

function Assert-LovionAutomationNotCancelled {
    if ([LovionBatchInput]::IsMouseGuardCancelled()) {
        [LovionBatchInput]::ReleaseModifiers()
        throw 'Lovion-automatisering gestopt omdat de muis handmatig is bewogen.'
    }
}

function Set-LovionWindowActive {
    for ($attempt = 0; $attempt -lt 4; $attempt += 1) {
        Assert-LovionAutomationNotCancelled
        $activated = [LovionBatchInput]::ActivateLovionWindow()
        Start-Sleep -Milliseconds 180
        Assert-LovionAutomationNotCancelled
        if ([LovionBatchInput]::IsLovionForegroundWindow()) {
            return $true
        }
        if (-not $activated) {
            Start-Sleep -Milliseconds 120
        }
    }
    return $false
}

function Get-LovionOcrSnapshot {
    param(
        [string]$ImagePath,
        [switch]$UseLovionWindow,
        [switch]$FullWindow,
        [switch]$TableHeader,
        [switch]$CountersOnly,
        [switch]$TransformerTable,
        [ValidateRange(1, 3)][int]$OcrScale = 1
    )

    if (-not $script:WinRtAsTaskMethod -or -not $script:BitmapDecoderType -or -not $script:SoftwareBitmapType -or -not $script:OcrResultType -or -not $script:OcrEngineType) {
        return $null
    }

    $sourceBitmap = $null
    $counterBitmap = $null
    $stream = $null
    $softwareBitmap = $null
    $randomAccessStream = $null
    try {
        if (-not [string]::IsNullOrWhiteSpace($ImagePath)) {
            $resolvedImagePath = (Resolve-Path -LiteralPath $ImagePath).Path
            $sourceBitmap = New-Object System.Drawing.Bitmap($resolvedImagePath)
            $width = $sourceBitmap.Width
            $height = $sourceBitmap.Height
        }
        else {
            $window = if ($UseLovionWindow) { [LovionBatchInput]::GetLovionWindow() } else { [LovionBatchInput]::GetForegroundWindow() }
            $rect = New-Object LovionBatchInput+RECT
            if ($window -eq [IntPtr]::Zero -or -not [LovionBatchInput]::GetWindowRect($window, [ref]$rect)) {
                return $null
            }
            $width = $rect.Right - $rect.Left
            $height = $rect.Bottom - $rect.Top
            if ($width -lt 400 -or $height -lt 200) {
                return $null
            }

            $sourceBitmap = New-Object System.Drawing.Bitmap($width, $height)
            $graphics = [System.Drawing.Graphics]::FromImage($sourceBitmap)
            try {
                $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size($width, $height)))
            }
            finally {
                $graphics.Dispose()
            }
        }

        $cropX = if ($TransformerTable) { [int][Math]::Floor($width * 0.45) } elseif ($CountersOnly) { [int][Math]::Floor($width * 0.70) } elseif ($FullWindow -or $TableHeader) { 0 } else { [int][Math]::Floor($width * 0.45) }
        $cropY = if ($TransformerTable) { [int][Math]::Floor($height * 0.55) } else { 0 }
        $cropHeight = if ($TransformerTable) { $height - $cropY } elseif ($FullWindow -and -not $TableHeader) { $height } else { [Math]::Min(420, [int][Math]::Ceiling($height * 0.40)) }
        $cropRectangle = New-Object System.Drawing.Rectangle($cropX, $cropY, ($width - $cropX), $cropHeight)
        $counterBitmap = $sourceBitmap.Clone($cropRectangle, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $actualScale = 1.0
        if ($OcrScale -gt 1) {
            $actualScale = [Math]::Min([double]$OcrScale, [double]$script:OcrEngineType::MaxImageDimension / [Math]::Max($counterBitmap.Width, $counterBitmap.Height))
            if ($actualScale -gt 1.0) {
                $scaledBitmap = New-Object System.Drawing.Bitmap([int][Math]::Round($counterBitmap.Width * $actualScale), [int][Math]::Round($counterBitmap.Height * $actualScale))
                $scaleGraphics = [System.Drawing.Graphics]::FromImage($scaledBitmap)
                try {
                    $scaleGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                    $scaleGraphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
                    $scaleGraphics.DrawImage($counterBitmap, 0, 0, $scaledBitmap.Width, $scaledBitmap.Height)
                }
                finally { $scaleGraphics.Dispose() }
                $counterBitmap.Dispose()
                $counterBitmap = $scaledBitmap
            }
            else { $actualScale = 1.0 }
        }
        $stream = New-Object System.IO.MemoryStream
        $counterBitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
        $stream.Position = 0

        $randomAccessStream = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($stream)
        $decoderOperation = $script:BitmapDecoderType::CreateAsync($randomAccessStream)
        $decoderTask = $script:WinRtAsTaskMethod.MakeGenericMethod($script:BitmapDecoderType).Invoke($null, @($decoderOperation))
        $decoderTask.Wait()
        $decoder = $decoderTask.Result

        $bitmapOperation = $decoder.GetSoftwareBitmapAsync()
        $bitmapTask = $script:WinRtAsTaskMethod.MakeGenericMethod($script:SoftwareBitmapType).Invoke($null, @($bitmapOperation))
        $bitmapTask.Wait()
        $softwareBitmap = $bitmapTask.Result

        $ocrEngine = $script:LovionOcrEngine
        if (-not $ocrEngine) { $ocrEngine = $script:OcrEngineType::TryCreateFromUserProfileLanguages() }
        if (-not $ocrEngine) {
            $language = $script:OcrEngineType::AvailableRecognizerLanguages |
                Where-Object { $_.LanguageTag -in @('nl-NL', 'en-US') } |
                Select-Object -First 1
            if ($language) {
                $ocrEngine = $script:OcrEngineType::TryCreateFromLanguage($language)
            }
        }
        if (-not $ocrEngine) {
            return $null
        }
        $script:LovionOcrEngine = $ocrEngine

        $ocrOperation = $ocrEngine.RecognizeAsync($softwareBitmap)
        $ocrTask = $script:WinRtAsTaskMethod.MakeGenericMethod($script:OcrResultType).Invoke($null, @($ocrOperation))
        $ocrTask.Wait()
        $ocrText = [string]::Join([Environment]::NewLine, @($ocrTask.Result.Lines | ForEach-Object { $_.Text }))

        $lineItems = New-Object System.Collections.Generic.List[object]
        $wordItems = New-Object System.Collections.Generic.List[object]
        foreach ($line in @($ocrTask.Result.Lines)) {
            $lineText = [string]$line.Text
            $lineWords = New-Object System.Collections.Generic.List[object]
            foreach ($word in @($line.Words)) {
                try {
                    $wordRect = $word.BoundingRect
                    $wordText = [string]$word.Text
                    if ([string]::IsNullOrWhiteSpace($wordText)) {
                        continue
                    }
                    $wordInfo = [pscustomobject]@{
                        Text = $wordText
                        X = ([double]$wordRect.X / $actualScale) + $cropX
                        Y = ([double]$wordRect.Y / $actualScale) + $cropY
                        Width = [double]$wordRect.Width / $actualScale
                        Height = [double]$wordRect.Height / $actualScale
                        CenterX = (([double]$wordRect.X + ([double]$wordRect.Width / 2.0)) / $actualScale) + $cropX
                        CenterY = (([double]$wordRect.Y + ([double]$wordRect.Height / 2.0)) / $actualScale) + $cropY
                    }
                    $lineWords.Add($wordInfo)
                    $wordItems.Add($wordInfo)
                }
                catch {
                    # Some OCR providers expose line text but no word rectangles.
                }
            }
            $lineItems.Add([pscustomobject]@{
                Text = $lineText
                Words = @($lineWords.ToArray())
            })
        }

        return [pscustomobject]@{
            Width = $width
            Height = $height
            CropX = $cropX
            CropY = $cropY
            CropHeight = $cropHeight
            rawText = $ocrText
            Lines = @($lineItems.ToArray())
            Words = @($wordItems.ToArray())
        }
    }
    catch {
        Write-LovionBatchLog ('OCR-fout: ' + $_.Exception.Message)
        return $null
    }
    finally {
        if ($softwareBitmap -is [System.IDisposable]) { ([System.IDisposable]$softwareBitmap).Dispose() }
        if ($randomAccessStream -is [System.IDisposable]) { ([System.IDisposable]$randomAccessStream).Dispose() }
        if ($stream) { $stream.Dispose() }
        if ($counterBitmap) { $counterBitmap.Dispose() }
        if ($sourceBitmap) { $sourceBitmap.Dispose() }
        # WIC decoders and OCR results also wrap native objects. Their native
        # allocations do not reliably trigger managed GC during a long run.
        $script:OcrSnapshotCount += 1
        if (($script:OcrSnapshotCount % 25) -eq 0) { [System.GC]::Collect() }
    }
}

function Get-LovionScreenCounters {
    param(
        [string]$ImagePath,
        [switch]$UseLovionWindow,
        [switch]$FullWindow,
        [switch]$TableHeader
    )

    $snapshot = Get-LovionOcrSnapshot @PSBoundParameters
    if ($null -eq $snapshot) {
        return $null
    }

    $values = @{}
    foreach ($item in @(
        @{ Name = 'loaded'; Pattern = 'Aantal\s+geladen' },
        @{ Name = 'filtered'; Pattern = 'Gefilterd' },
        @{ Name = 'selected'; Pattern = 'Geselecteerd' }
    )) {
        $match = [regex]::Match([string]$snapshot.rawText, ('(?i){0}\s*[:;]?\s*([0-9IOil|]+)' -f $item.Pattern))
        if ($match.Success) {
            $normalized = $match.Groups[1].Value.Replace('I', '1').Replace('i', '1').Replace('l', '1').Replace('|', '1').Replace('O', '0')
            $values[$item.Name] = [int]$normalized
        }
        else {
            $values[$item.Name] = $null
        }
    }

    # Small adjacent digits can be merged into a letter by Windows OCR (64
    # was read as ae/æ in the live station test). Never map that letter to a
    # guessed number: retry only the counter pane at a larger resolution.
    if ($null -eq $values['loaded'] -or $null -eq $values['filtered'] -or $null -eq $values['selected']) {
        $counterParameters = @{} + $PSBoundParameters
        $counterParameters['CountersOnly'] = $true
        $counterParameters['OcrScale'] = 2
        $counterSnapshot = Get-LovionOcrSnapshot @counterParameters
        if ($null -ne $counterSnapshot) {
            foreach ($item in @(
                @{ Name = 'loaded'; Pattern = 'Aantal\s+geladen' },
                @{ Name = 'filtered'; Pattern = 'Gefilterd' },
                @{ Name = 'selected'; Pattern = 'Geselecteerd' }
            )) {
                if ($null -ne $values[$item.Name]) { continue }
                $match = [regex]::Match([string]$counterSnapshot.rawText, ('(?i){0}\s*[:;]?\s*([0-9IOil|]+)' -f $item.Pattern))
                if ($match.Success) {
                    $normalized = $match.Groups[1].Value.Replace('I', '1').Replace('i', '1').Replace('l', '1').Replace('|', '1').Replace('O', '0')
                    $values[$item.Name] = [int]$normalized
                }
            }
        }
    }

    return [pscustomobject]@{
        loaded = $values['loaded']
        filtered = $values['filtered']
        selected = $values['selected']
        rawText = $snapshot.rawText
    }
}

function Normalize-LovionOcrToken {
    param([string]$Value)

    if ($null -eq $Value) {
        return ''
    }
    return (([string]$Value).ToUpperInvariant() -replace '[^A-Z0-9]', '')
}

function Get-LovionOcrTokenDistance {
    param(
        [string]$Left,
        [string]$Right
    )

    $leftText = Normalize-LovionOcrToken $Left
    $rightText = Normalize-LovionOcrToken $Right
    if ($leftText -eq $rightText) {
        return 0
    }
    if ([string]::IsNullOrEmpty($leftText) -or [string]::IsNullOrEmpty($rightText)) {
        return [int]::MaxValue
    }

    $previous = New-Object int[] ($rightText.Length + 1)
    for ($j = 0; $j -le $rightText.Length; $j += 1) {
        $previous[$j] = $j
    }
    for ($i = 1; $i -le $leftText.Length; $i += 1) {
        $current = New-Object int[] ($rightText.Length + 1)
        $current[0] = $i
        for ($j = 1; $j -le $rightText.Length; $j += 1) {
            $cost = if ($leftText[$i - 1] -eq $rightText[$j - 1]) { 0 } else { 1 }
            $current[$j] = [Math]::Min(
                [Math]::Min($current[$j - 1] + 1, $previous[$j] + 1),
                $previous[$j - 1] + $cost
            )
        }
        $previous = $current
    }
    return $previous[$rightText.Length]
}

function Test-LovionOcrTokenMatch {
    param(
        [string]$Actual,
        [string]$Expected
    )

    $actualToken = Normalize-LovionOcrToken $Actual
    $expectedToken = Normalize-LovionOcrToken $Expected
    if ($actualToken -eq $expectedToken) {
        return 0
    }
    if ($expectedToken.Length -lt 5 -or $actualToken.Length -lt 5) {
        return $null
    }
    $distance = Get-LovionOcrTokenDistance -Left $actualToken -Right $expectedToken
    if ($distance -le 1) {
        return 1
    }
    return $null
}

function Test-LovionOcrBounds {
    param(
        [double]$X,
        [double]$Y,
        [double]$Width,
        [double]$Height,
        [Nullable[int]]$MinX,
        [Nullable[int]]$MaxX,
        [Nullable[int]]$MinY,
        [Nullable[int]]$MaxY
    )

    $centerX = $X + ($Width / 2.0)
    $centerY = $Y + ($Height / 2.0)
    if ($null -ne $MinX -and $centerX -lt [double]$MinX) { return $false }
    if ($null -ne $MaxX -and $centerX -gt [double]$MaxX) { return $false }
    if ($null -ne $MinY -and $centerY -lt [double]$MinY) { return $false }
    if ($null -ne $MaxY -and $centerY -gt [double]$MaxY) { return $false }
    return $true
}

function Find-LovionOcrTarget {
    param(
        [object]$Snapshot,
        [string]$TargetText,
        [string]$ExcludeText,
        [Nullable[int]]$MinX,
        [Nullable[int]]$MaxX,
        [Nullable[int]]$MinY,
        [Nullable[int]]$MaxY
    )

    if ($null -eq $Snapshot -or [string]::IsNullOrWhiteSpace($TargetText)) {
        return $null
    }

    $expectedTokens = @(
        $TargetText -split '\s+' |
            ForEach-Object { Normalize-LovionOcrToken $_ } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($expectedTokens.Count -eq 0) {
        return $null
    }
    $excludedToken = Normalize-LovionOcrToken $ExcludeText
    $candidates = New-Object System.Collections.Generic.List[object]

    foreach ($line in @($Snapshot.Lines)) {
        $lineWords = @($line.Words)
        if ($lineWords.Count -eq 0) {
            continue
        }

        $lineMatches = New-Object System.Collections.Generic.List[object]
        if ($expectedTokens.Count -eq 1) {
            foreach ($word in $lineWords) {
                $quality = Test-LovionOcrTokenMatch -Actual ([string]$word.Text) -Expected $expectedTokens[0]
                if ($null -ne $quality) {
                    $lineMatches.Add([pscustomobject]@{ Word = $word; Quality = [int]$quality })
                }
            }
        }
        else {
            for ($start = 0; $start -lt $lineWords.Count; $start += 1) {
                if ($start + $expectedTokens.Count -gt $lineWords.Count) {
                    break
                }
                $matchedWords = New-Object System.Collections.Generic.List[object]
                $totalQuality = 0
                $matched = $true
                for ($offset = 0; $offset -lt $expectedTokens.Count; $offset += 1) {
                    $word = $lineWords[$start + $offset]
                    $quality = Test-LovionOcrTokenMatch -Actual ([string]$word.Text) -Expected $expectedTokens[$offset]
                    if ($null -eq $quality) {
                        $matched = $false
                        break
                    }
                    $matchedWords.Add($word)
                    $totalQuality += [int]$quality
                }
                if ($matched) {
                    $lineMatches.Add([pscustomobject]@{ Word = $matchedWords.ToArray(); Quality = $totalQuality })
                }
            }

            # Lovion sometimes renders a two-word toolbar caption as one OCR word
            # (for example Startquery) or puts a separator between the words.
            # Match the compact caption as a single word as a second pass, while
            # keeping the same bounds check below.
            $compactExpected = ($expectedTokens -join '')
            foreach ($word in $lineWords) {
                $compactActual = Normalize-LovionOcrToken ([string]$word.Text)
                if ([string]::IsNullOrWhiteSpace($compactActual)) {
                    continue
                }
                if ($compactActual -eq $compactExpected) {
                    $lineMatches.Add([pscustomobject]@{ Word = @($word); Quality = 0 })
                    continue
                }
                if ($compactExpected.Length -ge 5 -and $compactActual.Length -ge 5) {
                    $compactDistance = Get-LovionOcrTokenDistance -Left $compactActual -Right $compactExpected
                    if ($compactDistance -le 1) {
                        $lineMatches.Add([pscustomobject]@{ Word = @($word); Quality = 1 })
                    }
                }
            }
        }

        foreach ($match in $lineMatches.ToArray()) {
            $matchedWords = @($match.Word)
            if ($matchedWords.Count -eq 0) {
                continue
            }
            if ($excludedToken -and (@($matchedWords | Where-Object { (Normalize-LovionOcrToken $_.Text) -eq $excludedToken }).Count -gt 0)) {
                continue
            }
            $left = [double](($matchedWords | Measure-Object X -Minimum).Minimum)
            $top = [double](($matchedWords | Measure-Object Y -Minimum).Minimum)
            $right = [double](($matchedWords | ForEach-Object { $_.X + $_.Width } | Measure-Object -Maximum).Maximum)
            $bottom = [double](($matchedWords | ForEach-Object { $_.Y + $_.Height } | Measure-Object -Maximum).Maximum)
            $boundsWidth = [Math]::Max(1.0, $right - $left)
            $boundsHeight = [Math]::Max(1.0, $bottom - $top)
            if (-not (Test-LovionOcrBounds -X $left -Y $top -Width $boundsWidth -Height $boundsHeight -MinX $MinX -MaxX $MaxX -MinY $MinY -MaxY $MaxY)) {
                continue
            }
            $candidates.Add([pscustomobject]@{
                Text = $TargetText
                MatchedText = (($matchedWords | ForEach-Object { $_.Text }) -join ' ')
                Quality = [int]$match.Quality
                X = $left
                Y = $top
                Width = $boundsWidth
                Height = $boundsHeight
                CenterX = $left + ($boundsWidth / 2.0)
                CenterY = $top + ($boundsHeight / 2.0)
            })
        }
    }

    # Toolbar buttons can wrap a caption over two OCR lines. In the live
    # Lovion layout "Start query" is rendered exactly that way: Start is at
    # y=106 and query at y=125, with both words sharing the same x-position.
    # Match nearby vertically stacked words as one target, then apply the same
    # region and exclusion checks as for a normal line match.
    if ($expectedTokens.Count -gt 1) {
        $allWords = @($Snapshot.Words)
        for ($start = 0; $start -lt $allWords.Count; $start += 1) {
            $firstWord = $allWords[$start]
            $firstQuality = Test-LovionOcrTokenMatch -Actual ([string]$firstWord.Text) -Expected $expectedTokens[0]
            if ($null -eq $firstQuality) {
                continue
            }

            $matchedWords = New-Object System.Collections.Generic.List[object]
            $matchedWords.Add($firstWord)
            $totalQuality = [int]$firstQuality
            $previousWord = $firstWord
            $matched = $true
            for ($offset = 1; $offset -lt $expectedTokens.Count; $offset += 1) {
                $bestNext = $null
                $bestScore = [double]::MaxValue
                foreach ($candidateWord in $allWords) {
                    $candidateQuality = Test-LovionOcrTokenMatch -Actual ([string]$candidateWord.Text) -Expected $expectedTokens[$offset]
                    if ($null -eq $candidateQuality) {
                        continue
                    }
                    $verticalDelta = [double]$candidateWord.CenterY - [double]$previousWord.CenterY
                    $horizontalDelta = [Math]::Abs([double]$candidateWord.CenterX - [double]$previousWord.CenterX)
                    $maxVerticalGap = [Math]::Max(42.0, [double]$previousWord.Height * 3.5)
                    $maxHorizontalGap = [Math]::Max(90.0, [double]$previousWord.Width * 2.5)
                    if ($verticalDelta -lt -4.0 -or $verticalDelta -gt $maxVerticalGap -or $horizontalDelta -gt $maxHorizontalGap) {
                        continue
                    }
                    $score = $verticalDelta + ($horizontalDelta * 0.35) + ([int]$candidateQuality * 100.0)
                    if ($score -lt $bestScore) {
                        $bestScore = $score
                        $bestNext = [pscustomobject]@{ Word = $candidateWord; Quality = [int]$candidateQuality }
                    }
                }
                if ($null -eq $bestNext) {
                    $matched = $false
                    break
                }
                $matchedWords.Add($bestNext.Word)
                $totalQuality += [int]$bestNext.Quality
                $previousWord = $bestNext.Word
            }

            if (-not $matched) {
                continue
            }
            if ($excludedToken -and (@($matchedWords | Where-Object { (Normalize-LovionOcrToken $_.Text) -eq $excludedToken }).Count -gt 0)) {
                continue
            }
            $left = [double](($matchedWords | Measure-Object X -Minimum).Minimum)
            $top = [double](($matchedWords | Measure-Object Y -Minimum).Minimum)
            $right = [double](($matchedWords | ForEach-Object { $_.X + $_.Width } | Measure-Object -Maximum).Maximum)
            $bottom = [double](($matchedWords | ForEach-Object { $_.Y + $_.Height } | Measure-Object -Maximum).Maximum)
            $boundsWidth = [Math]::Max(1.0, $right - $left)
            $boundsHeight = [Math]::Max(1.0, $bottom - $top)
            if (-not (Test-LovionOcrBounds -X $left -Y $top -Width $boundsWidth -Height $boundsHeight -MinX $MinX -MaxX $MaxX -MinY $MinY -MaxY $MaxY)) {
                continue
            }
            $candidates.Add([pscustomobject]@{
                Text = $TargetText
                MatchedText = (($matchedWords | ForEach-Object { $_.Text }) -join ' ')
                Quality = $totalQuality
                X = $left
                Y = $top
                Width = $boundsWidth
                Height = $boundsHeight
                CenterX = $left + ($boundsWidth / 2.0)
                CenterY = $top + ($boundsHeight / 2.0)
            })
        }
    }

    $winner = @($candidates | Sort-Object Quality, Y, X | Select-Object -First 1)
    if ($winner.Count -eq 0) {
        return $null
    }
    return $winner[0]
}

function Invoke-LovionKeyTap {
    param(
        [int]$VirtualKey,
        [int]$DelayMs = 40,
        [switch]$FastMouseMode
    )

    Assert-LovionAutomationNotCancelled
    [LovionBatchInput]::KeyDown($VirtualKey)
    Start-Sleep -Milliseconds 20
    [LovionBatchInput]::KeyUp($VirtualKey)
    if ($DelayMs -gt 0) {
        Start-Sleep -Milliseconds $DelayMs
    }
    Assert-LovionAutomationNotCancelled
}

function Set-LovionSelectionDelta {
    param(
        [int]$Delta,
        [int]$KeyDelayMs = 60
    )

    if ($Delta -eq 0) {
        return
    }

    $key = if ($Delta -gt 0) { 0x28 } else { 0x26 }
    # Keep one physical Shift key-down active for the complete arrow run.
    # This is the same interaction as the reliable manual Lovion workflow.
    [LovionBatchInput]::PhysicalKeyDown(0xA0)
    try {
        for ($index = 0; $index -lt [Math]::Abs($Delta); $index += 1) {
            Assert-LovionAutomationNotCancelled
            Start-Sleep -Milliseconds 35
            [LovionBatchInput]::PhysicalTap($key)
            if ($KeyDelayMs -gt 0) {
                Start-Sleep -Milliseconds $KeyDelayMs
            }
        }
    }
    finally {
        [LovionBatchInput]::PhysicalKeyUp(0xA0)
    }
    Start-Sleep -Milliseconds 50
}

function Invoke-LovionGridScroll {
    param(
        [int]$WheelSteps,
        [switch]$FastMouseMode
    )

    Assert-LovionAutomationNotCancelled
    $result = if ($FastMouseMode) {
        [LovionBatchInput]::ScrollLovionGridFast($WheelSteps)
    }
    else {
        [LovionBatchInput]::ScrollLovionGrid($WheelSteps)
    }
    Assert-LovionAutomationNotCancelled
    return $result
}

function Invoke-LovionShiftClickRow {
    param(
        [int]$VisibleRowIndex,
        [switch]$FastMouseMode
    )

    Assert-LovionAutomationNotCancelled
    $result = if ($FastMouseMode) {
        [LovionBatchInput]::ShiftClickLovionGridRowFast($VisibleRowIndex)
    }
    else {
        [LovionBatchInput]::ShiftClickLovionGridRow($VisibleRowIndex)
    }
    Assert-LovionAutomationNotCancelled
    return $result
}

function Invoke-LovionClickRow {
    param(
        [int]$VisibleRowIndex,
        [switch]$FastMouseMode
    )

    Assert-LovionAutomationNotCancelled
    $result = if ($FastMouseMode) {
        [LovionBatchInput]::ClickLovionGridRowFast($VisibleRowIndex)
    }
    else {
        [LovionBatchInput]::ClickLovionGridRow($VisibleRowIndex)
    }
    Assert-LovionAutomationNotCancelled
    return $result
}

function Invoke-LovionClipboardExportMenu {
    param([switch]$FastMouseMode)

    Assert-LovionAutomationNotCancelled
    $result = if ($FastMouseMode) {
        [LovionBatchInput]::ExportLovionSelectionToClipboardFast()
    }
    else {
        [LovionBatchInput]::ExportLovionSelectionToClipboard()
    }
    Assert-LovionAutomationNotCancelled
    return $result
}

function Wait-LovionTransformerResultRowPoint {
    param(
        [int]$VisibleRowIndex,
        [int]$TimeoutSeconds = 35,
        [int]$PollMilliseconds = 550
    )

    $boundedRowIndex = [Math]::Max(0, [Math]::Min(13, $VisibleRowIndex))
    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))

    do {
        Assert-LovionAutomationNotCancelled
        if (-not (Set-LovionWindowActive)) {
            Start-Sleep -Milliseconds $PollMilliseconds
            continue
        }

        # The generic connection-grid coordinates are deliberately not used here.
        # The transformer results are in Lovion's lower-right table, and its
        # position can move when Citrix/Lovion renders slowly or is resized.
        $snapshot = Get-LovionOcrSnapshot -UseLovionWindow -FullWindow
        if ($null -ne $snapshot) {
            $header = $null
            foreach ($headerText in @('Master Asset ID', 'Master Asset', 'Asset ID')) {
                $candidate = Find-LovionOcrTarget -Snapshot $snapshot -TargetText $headerText
                if ($null -eq $candidate) {
                    continue
                }

                # Require the result-table header to be in the lower-right pane.
                # This prevents a similarly named item in the left navigation tree
                # from ever becoming the click anchor.
                if ($candidate.CenterX -lt ($snapshot.Width * 0.45) -or $candidate.CenterY -lt ($snapshot.Height * 0.45)) {
                    continue
                }
                $header = $candidate
                break
            }

            if ($null -ne $header) {
                $rowX = [int][Math]::Round($header.CenterX)
                # In the result grid the first data row starts approximately one
                # row-height below the column header. Keep the same 22 px row pitch
                # used by Lovion's grid navigation, but anchor it to OCR geometry.
                $rowY = [int][Math]::Round($header.Y + $header.Height + 20 + ($boundedRowIndex * 22))
                if ($rowX -ge 0 -and $rowX -lt $snapshot.Width -and $rowY -ge ($header.Y + $header.Height) -and $rowY -lt ($snapshot.Height - 100)) {
                    Write-LovionBatchLog ("Trafo-resultaatrij {0} via OCR gevonden: kolomkop '{1}' op ({2},{3}), klik op ({4},{5})." -f ($boundedRowIndex + 1), $header.MatchedText, [int]$header.CenterX, [int]$header.CenterY, $rowX, $rowY)
                    return [pscustomobject]@{
                        X = $rowX
                        Y = $rowY
                        HeaderText = [string]$header.MatchedText
                        HeaderX = [int][Math]::Round($header.CenterX)
                        HeaderY = [int][Math]::Round($header.CenterY)
                    }
                }
            }
        }

        Start-Sleep -Milliseconds $PollMilliseconds
    } while ((Get-Date) -lt $deadline)

    return $null
}

function Get-LovionTransformerMetadataFromSnapshot {
    param([object]$Snapshot, [int]$TransformerIndex)

    if ($null -eq $Snapshot) { return $null }
    $assetHeader = Find-LovionOcrTarget -Snapshot $Snapshot -TargetText 'Master Asset ID' -MinX ([int]($Snapshot.Width * 0.45)) -MinY ([int]($Snapshot.Height * 0.45))
    if ($null -eq $assetHeader) { return $null }
    $statusHeader = Find-LovionOcrTarget -Snapshot $Snapshot -TargetText 'Status' -MinX ([int]$assetHeader.X) -MinY ([int]($assetHeader.Y - 8)) -MaxY ([int]($assetHeader.Y + $assetHeader.Height + 8))
    if ($null -eq $statusHeader) { return $null }
    $rowY = [double]$assetHeader.Y + [double]$assetHeader.Height + 20 + ($TransformerIndex * 22)
    $nextHeader = @($Snapshot.Words | Where-Object {
        [Math]::Abs($_.CenterY - $statusHeader.CenterY) -le 8 -and $_.X -gt ($statusHeader.X + $statusHeader.Width + 4)
    } | Sort-Object X | Select-Object -First 1)
    $statusRight = if ($nextHeader.Count -gt 0) { [double]$nextHeader[0].X - 2 } else { [double]$statusHeader.X + 100 }
    $rowWords = @($Snapshot.Words | Where-Object {
        $_.CenterX -ge ($Snapshot.Width * 0.45) -and [Math]::Abs($_.CenterY - $rowY) -le 9
    } | Sort-Object X)
    $statusWords = @($rowWords | Where-Object { $_.CenterX -ge ($statusHeader.X - 8) -and $_.CenterX -lt $statusRight })
    $statusText = ($statusWords | ForEach-Object { $_.Text }) -join ' '
    $normalizedStatus = Normalize-LovionOcrToken $statusText
    $status = if ($normalizedStatus -eq 'GEPLAND') { 'gepland' } elseif ($normalizedStatus -eq 'INBEDRIJF') { 'in bedrijf' } else { $statusText.Trim() }
    if ([string]::IsNullOrWhiteSpace($status)) { return $null }
    $assetIds = @($rowWords | Where-Object { $_.Text -match '^\d{10,20}$' } | Select-Object -First 1)
    return [pscustomobject]@{
        Status = $status
        IsPlanned = $normalizedStatus -eq 'GEPLAND'
        AssetId = if ($assetIds.Count -gt 0) { [string]$assetIds[0].Text } else { '' }
        X = [int][Math]::Round($assetHeader.CenterX)
        Y = [int][Math]::Round($rowY)
        TransformerIndex = $TransformerIndex
    }
}

function Wait-LovionTransformerMetadata {
    param([int]$TransformerIndex, [int]$TimeoutSeconds = 15)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        Assert-LovionAutomationNotCancelled
        if (Set-LovionWindowActive) {
            $snapshot = Get-LovionOcrSnapshot -UseLovionWindow -TransformerTable -OcrScale 3
            $metadata = Get-LovionTransformerMetadataFromSnapshot -Snapshot $snapshot -TransformerIndex $TransformerIndex
            if ($null -ne $metadata) { return $metadata }
        }
        Start-Sleep -Milliseconds 450
    } while ((Get-Date) -lt $deadline)
    return $null
}

function Get-LovionSelectedCount {
    param([switch]$FastMouseMode)

    Assert-LovionAutomationNotCancelled
    # Connection selections use the upper table counter. Transformer query
    # selections use the bottom-right status bar, requiring a full-window
    # fallback when the focused table-header scan has no selected counter.
    $counters = Get-LovionScreenCounters -UseLovionWindow -TableHeader
    if ($null -eq $counters -or $null -eq $counters.selected) {
        $counters = Get-LovionScreenCounters -UseLovionWindow -FullWindow
    }
    Assert-LovionAutomationNotCancelled
    if ($null -eq $counters -or $null -eq $counters.selected) {
        return $null
    }
    return [int]$counters.selected
}

function Wait-LovionSelectedCount {
    param(
        [int]$TargetCount,
        [int]$TimeoutSeconds = 20,
        [switch]$FastMouseMode
    )

    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
    $selectedCount = $null
    $stableMatches = 0
    do {
        Assert-LovionAutomationNotCancelled
        $selectedCount = Get-LovionSelectedCount -FastMouseMode:$FastMouseMode
        if ($selectedCount -eq $TargetCount) {
            $stableMatches += 1
            if ($stableMatches -ge 2) {
                return $selectedCount
            }
        }
        else {
            $stableMatches = 0
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    return $selectedCount
}

function Move-LovionToNextStartRow {
    param(
        [int]$ActiveRowIndex,
        [int]$StartRowIndex,
        [int]$NetWheelSteps,
        [switch]$FastMouseMode
    )

    $boundedActiveRowIndex = [Math]::Max(0, [Math]::Min(13, $ActiveRowIndex))
    [LovionBatchInput]::ReleaseModifiers()
    Start-Sleep -Milliseconds 120
    if (-not (Invoke-LovionClickRow -VisibleRowIndex $boundedActiveRowIndex -FastMouseMode:$FastMouseMode)) {
        throw 'De actieve Lovion-eindrij kon niet worden gefocust voor de volgende batch.'
    }
    Start-Sleep -Milliseconds 220
    # The next batch starts with one plain Down: Shift is deliberately up.
    [LovionBatchInput]::PhysicalTap(0x28)
    Start-Sleep -Milliseconds 160
    [LovionBatchInput]::ReleaseModifiers()
    Start-Sleep -Milliseconds 450

    $nextCount = $null
    $selectionDeadline = [DateTime]::UtcNow.AddSeconds(12)
    do {
        $nextCount = Get-LovionSelectedCount -FastMouseMode:$FastMouseMode
        if ($nextCount -eq 1) {
            break
        }
        Start-Sleep -Milliseconds 400
    } while ([DateTime]::UtcNow -lt $selectionDeadline)
    Write-LovionBatchLog ("Volgende batchstart na Shift los + Down: geselecteerd={0}" -f $nextCount)
    if ($nextCount -ne 1) {
        $nextVisibleRowIndex = [Math]::Min(13, $boundedActiveRowIndex + 1)
        [LovionBatchInput]::ReleaseModifiers()
        if (-not (Invoke-LovionClickRow -VisibleRowIndex $nextVisibleRowIndex -FastMouseMode:$FastMouseMode)) {
            throw 'De volgende Lovion-startregel kon niet als enkele rij worden aangeklikt.'
        }
        Start-Sleep -Milliseconds 500
        $nextCount = Get-LovionSelectedCount -FastMouseMode:$FastMouseMode
        Write-LovionBatchLog ("Volgende batchstart na herstelklik: geselecteerd={0}" -f $nextCount)
        if ($nextCount -ne 1) {
            throw ("De volgende Lovion-batch start niet met 1 geselecteerde rij; Geselecteerd toont {0}." -f $nextCount)
        }
    }
    return [Math]::Min(13, $boundedActiveRowIndex + 1)
}

function Copy-LovionSelectionText {
    param(
        [int]$CopyWaitMs = 100,
        [int]$ExpectedRowCount = 0,
        [switch]$FastMouseMode
    )

    $maximumCopyAttempts = 3
    $maximumPollAttempts = 120
    $lastContent = ''
    for ($copyAttempt = 0; $copyAttempt -lt $maximumCopyAttempts; $copyAttempt += 1) {
        Assert-LovionAutomationNotCancelled
        try { [System.Windows.Forms.Clipboard]::Clear() } catch {}
        if (-not (Invoke-LovionClipboardExportMenu -FastMouseMode:$FastMouseMode)) {
            throw 'Het Lovion-menu Exporteren > Kopieer naar klembord kon niet worden bediend.'
        }

        Start-Sleep -Milliseconds ($CopyWaitMs + ($copyAttempt * 500))
        for ($attempt = 0; $attempt -lt $maximumPollAttempts; $attempt += 1) {
            Assert-LovionAutomationNotCancelled
            try {
                $content = [System.Windows.Forms.Clipboard]::GetText()
                if (-not [string]::IsNullOrWhiteSpace($content)) {
                    $lastContent = $content
                    if ($ExpectedRowCount -le 0) {
                        Assert-LovionAutomationNotCancelled
                        return $content
                    }

                    $exportedRows = @(ConvertFrom-LovionClipboardContent -TextContent $content)
                    $exportedCount = Get-CollectionCount $exportedRows
                    if ($exportedCount -eq $ExpectedRowCount) {
                        Write-LovionBatchLog ("Klembordexport gecontroleerd: {0} rijen." -f $exportedCount)
                        Assert-LovionAutomationNotCancelled
                        return $content
                    }
                }
            }
            catch {}
            Start-Sleep -Milliseconds 150
        }
        if (-not [string]::IsNullOrWhiteSpace($lastContent)) {
            $lastRows = @(ConvertFrom-LovionClipboardContent -TextContent $lastContent)
            Write-LovionBatchLog ("Klembordexportpoging {0} leverde {1} rijen; doel={2}. Opnieuw proberen." -f ($copyAttempt + 1), (Get-CollectionCount $lastRows), $ExpectedRowCount)
        }
        [LovionBatchInput]::ReleaseModifiers()
        Invoke-LovionKeyTap -VirtualKey 0x1B -DelayMs 100 -FastMouseMode:$FastMouseMode
        Start-Sleep -Milliseconds 650
    }
    return $lastContent
}

function Get-NormalizedLovionSelection {
    param(
        [int]$TargetCount,
        [Nullable[int]]$SelectedHint,
        [int]$StartRowIndex = 0,
        [int]$KeyDelayMs = 60,
        [int]$CopyWaitMs = 100,
        [int]$MaxCorrections = 6,
        [switch]$FastMouseMode
    )

    $lastVisibleRowIndex = 13
    $activeRowIndex = [Math]::Max(0, [Math]::Min($lastVisibleRowIndex, $StartRowIndex))
    $netWheelSteps = 0
    $selectedCount = if ($TargetCount -eq 1) { 1 } else { $null }

    if ($TargetCount -gt 1) {
        Set-LovionBatchStatus ("Lovion selectie: {0} rijen via toetsenbord" -f $TargetCount)
        Set-LovionSelectionDelta -Delta ($TargetCount - 1) -KeyDelayMs $KeyDelayMs
        $activeRowIndex = if ($TargetCount -le ($lastVisibleRowIndex + 1)) { $TargetCount - 1 } else { $lastVisibleRowIndex }
        $selectedCount = Wait-LovionSelectedCount -TargetCount $TargetCount -TimeoutSeconds 20 -FastMouseMode:$FastMouseMode
        Write-LovionBatchLog ("Toetsenbordselectie: geselecteerd={0}, doel={1}." -f $selectedCount, $TargetCount)
    }

    $lastObservedSelectedCount = $null
    for ($attempt = 0; $attempt -le $MaxCorrections -and $selectedCount -ne $TargetCount; $attempt += 1) {
        Start-Sleep -Milliseconds 450
        $observedSelectedCount = Get-LovionSelectedCount -FastMouseMode:$FastMouseMode
        $selectedCount = $observedSelectedCount
        Write-LovionBatchLog ("Toetsenbordselectie OCR {0}: geselecteerd={1}, doel={2}" -f ($attempt + 1), $selectedCount, $TargetCount)
        if ($null -eq $selectedCount) {
            if ($attempt -lt $MaxCorrections) {
                Start-Sleep -Milliseconds 350
                continue
            }
            throw 'De teller Geselecteerd kon na meerdere pogingen niet worden gelezen.'
        }
        if ($selectedCount -eq $TargetCount) {
            break
        }
        if ($null -ne $lastObservedSelectedCount -and $selectedCount -eq $lastObservedSelectedCount) {
            throw ("De Lovion-selectie veranderde niet na een correctiepoging; teller blijft {0} in plaats van {1}." -f $selectedCount, $TargetCount)
        }

        $delta = $TargetCount - $selectedCount
        $lastObservedSelectedCount = $selectedCount
        Set-LovionBatchStatus ("Lovion toetsenbordselectie corrigeren: {0} -> {1}" -f $selectedCount, $TargetCount)
        Set-LovionSelectionDelta -Delta $delta -KeyDelayMs $KeyDelayMs
        $activeRowIndex = if ($TargetCount -le ($lastVisibleRowIndex + 1)) { $TargetCount - 1 } else { $lastVisibleRowIndex }
        $selectedCount = Wait-LovionSelectedCount -TargetCount $TargetCount -TimeoutSeconds 20 -FastMouseMode:$FastMouseMode
        Write-LovionBatchLog ("Toetsenbordcorrectie: delta={0}, geselecteerd={1}, doel={2}." -f $delta, $selectedCount, $TargetCount)
        Start-Sleep -Milliseconds 400
    }

    if ($selectedCount -ne $TargetCount) {
        throw ("Lovion toont Geselecteerd: {0}, maar het doel is {1}." -f $selectedCount, $TargetCount)
    }

    $content = Copy-LovionSelectionText -CopyWaitMs $CopyWaitMs -ExpectedRowCount $TargetCount -FastMouseMode:$FastMouseMode
    Assert-LovionAutomationNotCancelled
    $rows = @(ConvertFrom-LovionClipboardContent -TextContent $content)
    $currentCount = Get-CollectionCount $rows
    Write-LovionBatchLog ("Lovion klembordexport na scrollselectie: {0} rijen, doel {1}" -f $currentCount, $TargetCount)
    if ($currentCount -le 0) {
        throw 'Lovion Exporteren > Kopieer naar klembord leverde geen herkenbare tekstexport op.'
    }
    if ($currentCount -ne $TargetCount) {
        throw ("Lovion toont {0} geselecteerde rijen, maar de klembordexport leverde {1} rijen op." -f $TargetCount, $currentCount)
    }

    return [pscustomobject]@{
        Text = $content
        Rows = $rows
        Count = $currentCount
        ActiveRowIndex = $activeRowIndex
        NetWheelSteps = $netWheelSteps
    }
}

function Invoke-LovionBatchImport {
    param(
        [string]$SourcePrefix,
        [switch]$FastMouseMode,
        [switch]$SkipCountdown,
        [switch]$UseExactSourceName,
        [string]$SourceType = 'LovionBatch'
    )

    if (-not [LovionBatchInput]::StartMouseGuard()) {
        throw 'De muisbewaking voor de Lovion-automatisering kon niet worden gestart.'
    }
    try {
        return Invoke-LovionBatchImportCore @PSBoundParameters
    }
    finally {
        [LovionBatchInput]::ReleaseModifiers()
        [LovionBatchInput]::StopMouseGuard()
    }
}

function Invoke-LovionBatchImportCore {
    param(
        [string]$SourcePrefix,
        [switch]$FastMouseMode,
        [switch]$SkipCountdown,
        [switch]$UseExactSourceName,
        [string]$SourceType = 'LovionBatch'
    )

    $batchSize = 100
    # Citrix can acknowledge the arrow key after a noticeable delay.  A
    # slightly slower physical-key cadence prevents dropped Shift+Down events.
    $keyDelayMs = 140
    $copyWaitMs = 250
    $maxCorrections = 6
    $importedCount = 0
    $completedBatches = 0
    $previousContent = $null
    $startRowIndex = 0
    $batchSummaries = New-Object System.Collections.Generic.List[string]

    Write-LovionBatchLog ("Start batchimport. SourcePrefix={0}; FastMouseMode={1}" -f $SourcePrefix, $FastMouseMode)
    if (-not (Set-LovionWindowActive)) {
        throw 'Het Citrix-venster met titel Lovion BIS kon niet automatisch actief worden gemaakt.'
    }
    Write-LovionBatchLog 'Lovion BIS venster actief gemaakt.'

    if (-not $SkipCountdown) {
        for ($secondsLeft = 5; $secondsLeft -gt 0; $secondsLeft -= 1) {
            Assert-LovionAutomationNotCancelled
            $modeLabel = if ($FastMouseMode) { 'snelle batch' } else { 'batch' }
            Set-LovionBatchStatus ("Lovion {0} start over {1} seconden..." -f $modeLabel, $secondsLeft)
            Start-Sleep -Seconds 1
        }
    }

    if (-not (Set-LovionWindowActive)) {
        throw 'Lovion verloor de toetsenbordfocus voordat de batch kon starten.'
    }
    if ($FastMouseMode) {
        $focusedFirstRow = [LovionBatchInput]::FocusLovionGridFirstRowFast()
    }
    else {
        $focusedFirstRow = [LovionBatchInput]::FocusLovionGridFirstRow()
    }
    Assert-LovionAutomationNotCancelled
    if (-not $focusedFirstRow) {
        throw 'De eerste Lovion-tabelrij kon niet automatisch worden gefocust.'
    }
    Start-Sleep -Milliseconds 250
    Write-LovionBatchLog 'Eerste Lovion-tabelrij gefocust.'

    # Citrix can leave the viewport at a previous station's last selection.
    # Reset both the active row and the viewport before selecting any batch.
    [LovionBatchInput]::ReleaseModifiers()
    [LovionBatchInput]::Chord(0x11, 0x24)
    Start-Sleep -Milliseconds 900
    $beforeResetCounters = Get-LovionScreenCounters -UseLovionWindow -TableHeader
    $loadedForReset = if ($null -ne $beforeResetCounters -and $null -ne $beforeResetCounters.loaded) { [int]$beforeResetCounters.loaded } else { 300 }
    $scrollSteps = [Math]::Max(20, [int][Math]::Ceiling($loadedForReset / 3.0) + 8)
    if (-not (Invoke-LovionGridScroll -WheelSteps (-$scrollSteps) -FastMouseMode:$FastMouseMode)) {
        throw 'De aansluitingenlijst kon niet helemaal naar boven worden gescrold.'
    }
    [LovionBatchInput]::ReleaseModifiers()
    [LovionBatchInput]::Chord(0x11, 0x24)
    Start-Sleep -Milliseconds 700
    if ($FastMouseMode) {
        $focusedFirstRow = [LovionBatchInput]::FocusLovionGridFirstRowFast()
    }
    else {
        $focusedFirstRow = [LovionBatchInput]::FocusLovionGridFirstRow()
    }
    Assert-LovionAutomationNotCancelled
    if (-not $focusedFirstRow) {
        throw 'De eerste Lovion-tabelrij kon na Ctrl+Home niet opnieuw worden gefocust.'
    }
    Start-Sleep -Milliseconds 300
    $firstSelectedCount = Wait-LovionSelectedCount -TargetCount 1 -TimeoutSeconds 12 -FastMouseMode:$FastMouseMode
    if ($firstSelectedCount -ne 1) { throw 'Na het naar boven scrollen is niet precies de eerste aansluiting geselecteerd.' }
    Write-LovionBatchLog ("Lovion-resultaatgrid helemaal naar boven gescrold ({0} wielstappen) en eerste rij geselecteerd." -f $scrollSteps)

    $counters = Get-LovionScreenCounters
    Assert-LovionAutomationNotCancelled
    $totalTarget = $null
    $selectedHint = [Nullable[int]]$null
    if ($null -ne $counters) {
        if ($null -ne $counters.loaded) {
            $totalTarget = [int]$counters.loaded
        }
        elseif ($null -ne $counters.filtered) {
            $totalTarget = [int]$counters.filtered
        }
        if ($null -ne $counters.loaded -and $null -ne $counters.filtered -and [int]$counters.filtered -lt [int]$counters.loaded) {
            $totalTarget = [int]$counters.filtered
        }
        if ($null -ne $counters.selected -and [int]$counters.selected -gt 0) {
            $selectedHint = [Nullable[int]]([int]$counters.selected)
        }
        Write-LovionBatchLog ("Schermtellers: geladen={0}, gefilterd={1}, geselecteerd={2}" -f $counters.loaded, $counters.filtered, $counters.selected)
    }
    else {
        Write-LovionBatchLog 'Schermtellers niet herkend; klembordtelling wordt gebruikt.'
    }

    while ($true) {
        if (-not (Set-LovionWindowActive)) {
            throw 'Lovion kon tijdens de batch niet opnieuw actief worden gemaakt.'
        }
        $remaining = if ($null -eq $totalTarget) { $null } else { [Math]::Max(0, [int]$totalTarget - $importedCount) }
        if ($null -ne $remaining -and $remaining -eq 0) {
            break
        }
        $targetCount = if ($null -eq $remaining) { $batchSize } else { [Math]::Min($batchSize, [int]$remaining) }
        Set-LovionBatchStatus ("Lovion batch {0}: selectie controleren" -f ($completedBatches + 1))

        $hint = if ($completedBatches -eq 0) { $selectedHint } else { [Nullable[int]]$null }
        $selection = Get-NormalizedLovionSelection -TargetCount $targetCount -SelectedHint $hint -StartRowIndex $startRowIndex -KeyDelayMs $keyDelayMs -CopyWaitMs $copyWaitMs -MaxCorrections $maxCorrections -FastMouseMode:$FastMouseMode
        if ($selection.Count -gt $targetCount) {
            throw ("De selectie bevat {0} rijen in plaats van {1}. Deze batch is niet geimporteerd." -f $selection.Count, $targetCount)
        }
        if ($null -ne $totalTarget -and $selection.Count -ne $targetCount) {
            throw ("De selectie bevat {0} rijen in plaats van {1}. Deze batch is niet geimporteerd." -f $selection.Count, $targetCount)
        }
        if ($null -ne $previousContent -and $selection.Text -eq $previousContent) {
            throw 'Lovion leverde dezelfde selectie nogmaals op; de dubbele batch is niet geimporteerd.'
        }

        $sourceName = if ($UseExactSourceName) {
            $SourcePrefix
        }
        else {
            '{0}_{1:000}' -f $SourcePrefix, ($completedBatches + 1)
        }
        $preparedRows = @(
            foreach ($row in $selection.Rows) {
                New-PreparedRowObject -Row $row -SourceFile $sourceName -SourcePath '' -SourceType $SourceType
            }
        )
        Assert-LovionAutomationNotCancelled
        Add-RowsToTable -Rows $preparedRows

        $importedCount += $selection.Count
        $completedBatches += 1
        $previousContent = $selection.Text
        $batchSummaries.Add(("Batch {0}: {1} rijen" -f $completedBatches, $selection.Count))
        Write-LovionBatchLog ("Batch {0} geimporteerd: {1} rijen" -f $completedBatches, $selection.Count)

        if ($selection.Count -lt $targetCount -or ($selection.Count -lt $batchSize -and $null -eq $totalTarget)) {
            break
        }
        if ($null -ne $totalTarget -and $importedCount -ge [int]$totalTarget) {
            break
        }

        Set-LovionBatchStatus ("Lovion batch {0}: naar volgende startregel" -f $completedBatches)
        if (-not (Set-LovionWindowActive)) {
            throw 'Lovion kon niet worden geactiveerd voor de volgende batch.'
        }
        $startRowIndex = Move-LovionToNextStartRow -ActiveRowIndex ([int]$selection.ActiveRowIndex) -StartRowIndex $startRowIndex -NetWheelSteps ([int]$selection.NetWheelSteps) -FastMouseMode:$FastMouseMode
    }

    Assert-LovionAutomationNotCancelled
    return [pscustomobject]@{
        ImportedCount = $importedCount
        BatchCount = $completedBatches
        Summaries = $batchSummaries.ToArray()
        Counters = $counters
    }
}

function Start-LovionBatchImport {
    param([switch]$FastMouseMode)

    $defaultPrefix = if ($FastMouseMode) { 'LovionSnel' } else { 'LovionBatch' }
    $dialogTitle = if ($FastMouseMode) { 'Lovion 100 snel (test)' } else { 'Lovion 100-batches' }
    $defaultName = '{0}_{1}' -f $defaultPrefix, (Get-Date -Format 'yyyyMMdd_HHmmss')
    $sourcePrefix = Show-SourceNameDialog -DefaultName $defaultName -Title $dialogTitle
    if ($null -eq $sourcePrefix) {
        return
    }
    if ([string]::IsNullOrWhiteSpace($sourcePrefix)) {
        $sourcePrefix = $defaultName
    }

    $question = if ($FastMouseMode) {
        "Selecteer in Lovion alleen de eerste rij van de tabel.`n`nNa Ja wordt de Workbench geminimaliseerd en heb je 5 seconden. De cursor blijft op de laatst gebruikte Lovion-positie staan. Zodra je de muis zelf beweegt, stopt de automatisering. Lovion krijgt ook toetsenbordfocus: typ niet tijdens de batch.`n`nStarten?"
    }
    else {
        "Selecteer in Lovion alleen de eerste rij van de tabel.`n`nNa Ja wordt de Workbench geminimaliseerd en worden de rijen automatisch per 100 geselecteerd, gekopieerd en toegevoegd. De cursor blijft op de laatst gebruikte Lovion-positie staan. Zodra je de muis zelf beweegt, stopt de automatisering.`n`nStarten?"
    }
    $answer = [System.Windows.Forms.MessageBox]::Show($script:MainForm, $question, $dialogTitle, [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Question)
    if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) {
        return
    }

    $script:MainForm.WindowState = [System.Windows.Forms.FormWindowState]::Minimized
    [System.Windows.Forms.Application]::DoEvents()
    try {
        $result = Invoke-LovionBatchImport -SourcePrefix $sourcePrefix -FastMouseMode:$FastMouseMode
    }
    catch {
        Write-LovionBatchLog ("FOUT: {0}" -f $_.Exception.ToString())
        $script:MainForm.WindowState = [System.Windows.Forms.FormWindowState]::Normal
        $script:MainForm.Activate()
        Update-StatusBar
        $modeText = if ($FastMouseMode) { 'Lovion snelle batch' } else { 'Lovion batch' }
        Show-ErrorMessage ("{0} is afgebroken.`n`n{1}" -f $modeText, $_.Exception.Message)
        return
    }

    $script:MainForm.WindowState = [System.Windows.Forms.FormWindowState]::Normal
    $script:MainForm.Activate()
    Update-StatusBar
    Write-LovionBatchLog ("Klaar. Totaal toegevoegd: {0}" -f $result.ImportedCount)
    $details = if ((Get-CollectionCount $result.Summaries) -gt 0) { $result.Summaries -join "`n" } else { 'Geen rijen geimporteerd.' }
    $completedText = if ($FastMouseMode) { 'Lovion snelle batch klaar.' } else { 'Lovion batch klaar.' }
    Show-InfoMessage ("{0}`n`nTotaal toegevoegd: {1}`n`n{2}" -f $completedText, $result.ImportedCount, $details)
}

function Invoke-LovionStationClick {
    param(
        [int]$X,
        [int]$Y,
        [ValidateRange(1, 2)]
        [int]$ClickCount = 1,
        [int]$WaitMilliseconds = 250,
        [string]$Description = 'Lovion-onderdeel'
    )

    if (-not (Set-LovionWindowActive)) {
        throw 'Lovion kon niet worden geactiveerd.'
    }
    if (-not [LovionBatchInput]::ClickLovionRecordedPoint($X, $Y, $ClickCount)) {
        Assert-LovionAutomationNotCancelled
        throw ("{0} kon niet worden aangeklikt. Zet Lovion volledig zichtbaar op het linker scherm." -f $Description)
    }
    if ($WaitMilliseconds -gt 0) {
        Start-Sleep -Milliseconds $WaitMilliseconds
    }
    Assert-LovionAutomationNotCancelled
}

function Wait-LovionScreenPattern {
    param(
        [string]$Pattern,
        [int]$TimeoutSeconds = 15,
        [string]$Description = 'Lovion-scherm'
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (-not (Set-LovionWindowActive)) {
            Start-Sleep -Milliseconds 400
            continue
        }
        $snapshot = Get-LovionScreenCounters -FullWindow
        Assert-LovionAutomationNotCancelled
        if ($null -ne $snapshot -and [regex]::IsMatch([string]$snapshot.rawText, $Pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)) {
            return $snapshot
        }
        Start-Sleep -Milliseconds 600
    } while ((Get-Date) -lt $deadline)

    Write-LovionBatchLog ("Waarschuwing: {0} niet via OCR herkend binnen {1} seconden." -f $Description, $TimeoutSeconds)
    return $null
}

function Wait-LovionInitialStationQueryResults {
    param(
        [string]$PreviousRawText,
        [int]$TimeoutSeconds = 45
    )

    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
    $changed = [string]::IsNullOrWhiteSpace($PreviousRawText)
    $lastRawText = $null
    $stableReads = 0
    do {
        Assert-LovionAutomationNotCancelled
        if (-not (Set-LovionWindowActive)) {
            Start-Sleep -Milliseconds 450
            continue
        }

        $snapshot = Get-LovionScreenCounters -FullWindow
        Assert-LovionAutomationNotCancelled
        if ($null -ne $snapshot) {
            $rawText = [string]$snapshot.rawText
            if (-not $changed -and $rawText -ne $PreviousRawText) {
                $changed = $true
            }

            # For the first station query, Aantal geladen is the number of
            # transformer rows Lovion actually returned. Do not let a stale or
            # broader Gefilterd value inflate that count; only use it when the
            # loaded counter is unavailable.
            $resultCount = if ($null -ne $snapshot.loaded) {
                [Math]::Max(0, [int]$snapshot.loaded)
            }
            elseif ($null -ne $snapshot.filtered) {
                [Math]::Max(0, [int]$snapshot.filtered)
            }
            else {
                0
            }

            # Require the post-query OCR to differ from the pre-click screen
            # and to be stable for two reads. This avoids classifying the old
            # station's counters while Citrix is still processing Start query.
            if ($changed -and $resultCount -gt 0) {
                if ($rawText -eq $lastRawText) {
                    $stableReads += 1
                }
                else {
                    $stableReads = 0
                }
                $lastRawText = $rawText
                if ($stableReads -ge 1) {
                    return $snapshot
                }
            }
            else {
                $lastRawText = $rawText
                $stableReads = 0
            }
        }
        Start-Sleep -Milliseconds 550
    } while ((Get-Date) -lt $deadline)

    return $null
}

function Invoke-LovionStationOcrClick {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetText,
        [string]$Description = 'Lovion-knop',
        [string]$ExcludeText,
        [int]$TimeoutSeconds = 30,
        [int]$PollMilliseconds = 650,
        [ValidateRange(1, 2)]
        [int]$ClickCount = 1,
        [Nullable[int]]$MinX,
        [Nullable[int]]$MaxX,
        [Nullable[int]]$MinY,
        [Nullable[int]]$MaxY,
        [double]$MinXRatio = -1,
        [double]$MaxXRatio = -1,
        [double]$MinYRatio = -1,
        [double]$MaxYRatio = -1,
        [Nullable[int]]$FallbackRecordedX,
        [Nullable[int]]$FallbackRecordedY,
        [int]$FallbackAfterSeconds = 5,
        [int]$AfterClickMilliseconds = 350
    )

    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
    $fallbackDeadline = (Get-Date).AddSeconds([Math]::Max(0, $FallbackAfterSeconds))
    $lastOcrText = $null
    $targetSeenInOcr = $false
    $fallbackAttempted = $false
    do {
        Assert-LovionAutomationNotCancelled
        if (-not (Set-LovionWindowActive)) {
            Start-Sleep -Milliseconds 450
            continue
        }

        $snapshot = Get-LovionOcrSnapshot -UseLovionWindow -FullWindow
        Assert-LovionAutomationNotCancelled
        if ($null -ne $snapshot) {
            $ocrText = [string]$snapshot.rawText
            $compactOcrText = Normalize-LovionOcrToken $ocrText
            $compactTargetText = Normalize-LovionOcrToken $TargetText
            if ($compactTargetText.Length -ge 5 -and $compactOcrText.Contains($compactTargetText)) {
                $targetSeenInOcr = $true
            }
            if ($ocrText -ne $lastOcrText) {
                Write-LovionBatchLog ("OCR scherm gewijzigd tijdens zoeken naar '{0}': {1}" -f $TargetText, ($ocrText -replace '\s+', ' ').Trim())
                $lastOcrText = $ocrText
            }
            $resolvedMinX = if ($MinXRatio -ge 0) { [int][Math]::Floor([double]$snapshot.Width * $MinXRatio) } else { $MinX }
            $resolvedMaxX = if ($MaxXRatio -ge 0) { [int][Math]::Ceiling([double]$snapshot.Width * $MaxXRatio) } else { $MaxX }
            $resolvedMinY = if ($MinYRatio -ge 0) { [int][Math]::Floor([double]$snapshot.Height * $MinYRatio) } else { $MinY }
            $resolvedMaxY = if ($MaxYRatio -ge 0) { [int][Math]::Ceiling([double]$snapshot.Height * $MaxYRatio) } else { $MaxY }
            $target = Find-LovionOcrTarget -Snapshot $snapshot -TargetText $TargetText -ExcludeText $ExcludeText -MinX $resolvedMinX -MaxX $resolvedMaxX -MinY $resolvedMinY -MaxY $resolvedMaxY
            if ($null -ne $target) {
                $clickX = [int][Math]::Round([double]$target.CenterX)
                $clickY = [int][Math]::Round([double]$target.CenterY)
                Write-LovionBatchLog ("OCR klik '{0}' ({1}) op vensterpunt {2},{3}; gevonden als '{4}'" -f $TargetText, $Description, $clickX, $clickY, $target.MatchedText)
                if (-not [LovionBatchInput]::ClickLovionWindowPoint($clickX, $clickY, $ClickCount)) {
                    Assert-LovionAutomationNotCancelled
                    throw ("{0} kon niet worden aangeklikt op de via OCR gevonden positie." -f $Description)
                }
                if ($AfterClickMilliseconds -gt 0) {
                    Start-Sleep -Milliseconds $AfterClickMilliseconds
                }
                Assert-LovionAutomationNotCancelled
                return
            }

            # Keep OCR as the primary path. If Windows OCR can read the caption
            # but does not expose usable word rectangles, use the original
            # recorded point once as a guarded fallback. The next workflow step
            # still verifies that Lovion transitioned to the expected screen.
            if (-not $fallbackAttempted -and $targetSeenInOcr -and $null -ne $FallbackRecordedX -and $null -ne $FallbackRecordedY -and (Get-Date) -ge $fallbackDeadline) {
                $fallbackAttempted = $true
                Write-LovionBatchLog ("OCR zag '{0}', maar gaf geen klikpositie; guarded fallback op opgenomen punt {1},{2}." -f $TargetText, $FallbackRecordedX, $FallbackRecordedY)
                if (-not [LovionBatchInput]::ClickLovionRecordedPoint([int]$FallbackRecordedX, [int]$FallbackRecordedY, $ClickCount)) {
                    Assert-LovionAutomationNotCancelled
                    throw ("{0} kon niet worden aangeklikt op de fallbackpositie." -f $Description)
                }
                if ($AfterClickMilliseconds -gt 0) {
                    Start-Sleep -Milliseconds $AfterClickMilliseconds
                }
                Assert-LovionAutomationNotCancelled
                return
            }
        }
        Start-Sleep -Milliseconds ([Math]::Max(150, $PollMilliseconds))
    } while ((Get-Date) -lt $deadline)

    throw ("{0} ('{1}') werd niet binnen {2} seconden op het Lovion-scherm gevonden. Lovion lijkt nog te laden of het scherm wijkt af." -f $Description, $TargetText, $TimeoutSeconds)
}

function Get-LovionConnectionsTableEvidence {
    param([AllowNull()][object]$Snapshot)

    if ($null -eq $Snapshot) {
        return [pscustomobject]@{ Ready = $false; Headers = @(); HasCounter = $false }
    }
    # OCR can insert spaces/punctuation in a compact table header. Normalize
    # them before comparing; still require two connection-specific columns
    # and a row counter so a station-query result cannot be imported by mistake.
    $text = Normalize-LovionOcrToken ([string]$Snapshot.rawText)
    $headers = @(
        @('Gebruiksdoel', 'Aansluitmethode', 'Doorlaatwaarde') |
            Where-Object { $text.Contains((Normalize-LovionOcrToken $_)) }
    )
    $hasCounter = $null -ne $Snapshot.loaded -or $null -ne $Snapshot.filtered
    return [pscustomobject]@{
        Ready = $headers.Count -ge 2 -and $hasCounter
        Headers = $headers
        HasCounter = $hasCounter
    }
}

function Wait-LovionConnectionsTable {
    param([int]$TimeoutSeconds = 60)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $previousEvidence = $null
    do {
        if (Set-LovionWindowActive) {
            # Use the known Citrix/Lovion window rather than whichever transient
            # window has focus. Read the table/status band separately: the map
            # and property panel must not affect header/counter recognition.
            $snapshot = Get-LovionScreenCounters -UseLovionWindow -TableHeader
            Assert-LovionAutomationNotCancelled
            $evidence = Get-LovionConnectionsTableEvidence -Snapshot $snapshot
            if (-not $evidence.Ready) {
                # Older layouts may put their counters below the table.
                $fullSnapshot = Get-LovionScreenCounters -UseLovionWindow -FullWindow
                Assert-LovionAutomationNotCancelled
                $fullEvidence = Get-LovionConnectionsTableEvidence -Snapshot $fullSnapshot
                if ($fullEvidence.Ready) { return $fullSnapshot }
            }
            $loaded = if ($null -ne $snapshot) { $snapshot.loaded } else { $null }
            $filtered = if ($null -ne $snapshot) { $snapshot.filtered } else { $null }
            $rawText = if ($null -ne $snapshot) {
                (@([regex]::Matches([string]$snapshot.rawText, '(?i)(Aantal\s+geladen|Gefilterd|Geselecteerd)\s*[:;]?\s*[^\r\n]{0,80}') | ForEach-Object { $_.Value }) -join ' | ')
            } else { '<geen OCR-opname>' }
            $summary = 'kolommen={0}; geladen={1}; gefilterd={2}; OCR={3}' -f ($evidence.Headers -join ','), $loaded, $filtered, $rawText
            if ($summary -ne $previousEvidence) {
                Write-LovionBatchLog ('Herkenning aansluitingenlijst: ' + $summary)
                $previousEvidence = $summary
            }
            if ($evidence.Ready) { return $snapshot }
        }
        Start-Sleep -Milliseconds 650
    } while ((Get-Date) -lt $deadline)
    return $null
}

function Invoke-LovionStationViewClick {
    param([int]$TimeoutSeconds = 45)

    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
    $nextOpenRibbonRefresh = Get-Date
    do {
        Assert-LovionAutomationNotCancelled
        if (-not (Set-LovionWindowActive)) {
            Start-Sleep -Milliseconds 450
            continue
        }

        $snapshot = Get-LovionOcrSnapshot -UseLovionWindow -FullWindow
        Assert-LovionAutomationNotCancelled
        if ($null -ne $snapshot) {
            $view = Find-LovionOcrTarget -Snapshot $snapshot -TargetText 'VIEW' -MinX 0 -MaxX ([int][Math]::Ceiling($snapshot.Width * 0.18)) -MinY ([int][Math]::Floor($snapshot.Height * 0.04)) -MaxY ([int][Math]::Ceiling($snapshot.Height * 0.20))
            if ($null -ne $view) {
                $clickX = [int][Math]::Round([double]$view.CenterX)
                $clickY = [int][Math]::Round([double]$view.CenterY)
                Write-LovionBatchLog ("OCR klik '{0}' (VIEW na bijgewerkte Open-ribbon) op vensterpunt {1},{2}" -f $view.MatchedText, $clickX, $clickY)
                if (-not [LovionBatchInput]::ClickLovionWindowPoint($clickX, $clickY, 1)) {
                    Assert-LovionAutomationNotCancelled
                    throw 'VIEW kon niet worden aangeklikt op de gevonden positie.'
                }
                Start-Sleep -Milliseconds 1400
                Assert-LovionAutomationNotCancelled
                return
            }

            # When a slow Citrix response leaves the ribbon stale, clicking
            # the already visible Open tab once more refreshes its commands.
            if ((Get-Date) -ge $nextOpenRibbonRefresh) {
                $openTab = Find-LovionOcrTarget -Snapshot $snapshot -TargetText 'Open' -MinX ([int][Math]::Floor($snapshot.Width * 0.05)) -MaxX ([int][Math]::Ceiling($snapshot.Width * 0.10)) -MinY 0 -MaxY ([int][Math]::Ceiling($snapshot.Height * 0.10))
                if ($null -ne $openTab) {
                    $clickX = [int][Math]::Round([double]$openTab.CenterX)
                    $clickY = [int][Math]::Round([double]$openTab.CenterY)
                    Write-LovionBatchLog ("VIEW nog niet zichtbaar; Open-ribbon opnieuw geactiveerd op vensterpunt {0},{1}." -f $clickX, $clickY)
                    if (-not [LovionBatchInput]::ClickLovionWindowPoint($clickX, $clickY, 1)) {
                        Assert-LovionAutomationNotCancelled
                        throw 'De Open-ribbon kon niet opnieuw worden geactiveerd.'
                    }
                    $nextOpenRibbonRefresh = (Get-Date).AddSeconds(3)
                    Start-Sleep -Milliseconds 700
                    continue
                }
                $nextOpenRibbonRefresh = (Get-Date).AddSeconds(2)
            }
        }
        Start-Sleep -Milliseconds 550
    } while ((Get-Date) -lt $deadline)

    throw ("VIEW werd niet binnen {0} seconden zichtbaar na het openen van de query." -f $TimeoutSeconds)
}

function Test-LovionAmbiguousMapMarkers {
    param(
        [int[]]$Points,
        [int]$CenterX = 957,
        [int]$CenterY = 590,
        [int]$CenterTolerance = 45
    )

    $values = @($Points)
    $candidateCount = [int][Math]::Floor($values.Count / 2)
    if ($candidateCount -lt 2) {
        return $false
    }

    for ($index = 0; $index -lt $candidateCount; $index += 1) {
        $candidateX = [int]$values[$index * 2]
        $candidateY = [int]$values[($index * 2) + 1]
        $distance = [Math]::Sqrt(
            [Math]::Pow($candidateX - $CenterX, 2) +
            [Math]::Pow($candidateY - $CenterY, 2)
        )
        if ($distance -le $CenterTolerance) {
            return $false
        }
    }

    return $true
}

function Invoke-LovionStationMapSelection {
    param([string]$StationNumber)

    Invoke-LovionStationClick -X 66 -Y 89 -WaitMilliseconds 350 -Description 'de vlagfunctie'
    Invoke-LovionStationClick -X 957 -Y 590 -WaitMilliseconds 1200 -Description 'de standaardkaartpositie'
    if ($null -ne (Wait-LovionScreenPattern -Pattern 'Terug.?zetten|Reset' -TimeoutSeconds 8 -Description 'Terugzetten na de standaardkaartklik')) {
        return [pscustomobject]@{
            Selected = $true
            ManualRequired = $false
            CandidateCount = 1
        }
    }

    Write-LovionBatchLog ("Standaardkaartpositie leverde voor station {0} geen Terugzetten op; gele kaartmarkers worden gescand." -f $StationNumber)
    $points = @([LovionBatchInput]::FindLovionYellowMarkerPoints())
    $candidateCount = [int][Math]::Floor($points.Count / 2)
    if (Test-LovionAmbiguousMapMarkers -Points $points) {
        Write-LovionBatchLog ("Ambigu station {0}: {1} gele kaartmarkers en geen centrale marker; handmatige toevoeging aan de Lovion Coordinate Workbench-lijst vereist." -f $StationNumber, $candidateCount)
        return [pscustomobject]@{
            Selected = $false
            ManualRequired = $true
            CandidateCount = $candidateCount
        }
    }

    $tested = New-Object System.Collections.Generic.List[string]
    foreach ($index in 0..([Math]::Max(-1, ($candidateCount - 1))) ) {
        $candidateX = [int]$points[$index * 2]
        $candidateY = [int]$points[($index * 2) + 1]
        if ([Math]::Abs($candidateX - 957) -lt 30 -and [Math]::Abs($candidateY - 590) -lt 30) {
            continue
        }
        $tested.Add(("{0},{1}" -f $candidateX, $candidateY))
        Write-LovionBatchLog ("Kaartmarker {0}/{1} proberen op {2},{3} voor station {4}." -f $tested.Count, $candidateCount, $candidateX, $candidateY, $StationNumber)
        if (-not (Set-LovionWindowActive)) {
            Start-Sleep -Milliseconds 450
            continue
        }
        if (-not [LovionBatchInput]::ClickLovionWindowPoint($candidateX, $candidateY, 1)) {
            Assert-LovionAutomationNotCancelled
            continue
        }
        Start-Sleep -Milliseconds 900
        if ($null -ne (Wait-LovionScreenPattern -Pattern 'Terug.?zetten|Reset' -TimeoutSeconds 5 -Description 'Terugzetten na een gevonden kaartmarker')) {
            Write-LovionBatchLog ("Kaartmarker {0},{1} accepteerde station {2}; Terugzetten is zichtbaar." -f $candidateX, $candidateY, $StationNumber)
            return [pscustomobject]@{
                Selected = $true
                ManualRequired = $false
                CandidateCount = $candidateCount
            }
        }
    }

    throw ("Lovion heeft station {0} niet op de kaart geselecteerd; geen Terugzetten/Reset na de standaardklik of de gescande kaartmarkers." -f $StationNumber)
}

function Open-LovionConnectionsForStation {
    param(
        [string]$StationNumber,
        [int]$StationIndex,
        [int]$StationCount,
        [int]$TransformerIndex = 0,
        [Nullable[int]]$KnownTransformerCount,
        [switch]$ReuseCurrentStationResults
    )

    $actionText = if ($ReuseCurrentStationResults) { 'volgende trafo uit bestaande resultaten' } else { 'trafo zoeken' }
    Set-LovionBatchStatus ("Station {0}/{1}: trafo {2} {3} ({4})" -f $StationIndex, $StationCount, ($TransformerIndex + 1), $actionText, $StationNumber)
    Write-LovionBatchLog ("Stationsimport: station {0}/{1}, trafo {2} openen ({3}): {4}" -f $StationIndex, $StationCount, ($TransformerIndex + 1), $actionText, $StationNumber)

    if ($null -eq (Wait-LovionScreenPattern -Pattern 'LS\s+Stroomtransformatorgroep' -TimeoutSeconds 25 -Description 'de startlijst LS Stroomtransformatorgroep')) {
        throw 'De startlijst LS Stroomtransformatorgroep is niet zichtbaar. Open deze lijst in Lovion voordat je de stationsimport start.'
    }

    if ($ReuseCurrentStationResults) {
        if ($null -eq $KnownTransformerCount -or [int]$KnownTransformerCount -lt 1) {
            throw ("Station {0} heeft geen geldig eerder gelezen trafo-aantal voor hergebruik van de resultatenlijst." -f $StationNumber)
        }
        $initialResultCount = [Math]::Max(0, [int]$KnownTransformerCount)
        Write-LovionBatchLog ("Station {0}: bestaande eerste resultaten hergebruiken; Aantal geladen={1}; geen nieuwe stationzoekactie." -f $StationNumber, $initialResultCount)
    }
    else {
        Invoke-LovionStationClick -X 1127 -Y 285 -WaitMilliseconds 180 -Description 'de stationslijst'
        [LovionBatchInput]::Chord(0x11, 0x41)
        Start-Sleep -Milliseconds 100
        Assert-LovionAutomationNotCancelled
        if (-not [LovionBatchInput]::TypeUnicodeText($StationNumber)) {
            Assert-LovionAutomationNotCancelled
            throw ("Stationnummer {0} kon niet in Lovion worden ingevoerd." -f $StationNumber)
        }
        if ($null -eq (Wait-LovionScreenPattern -Pattern ([regex]::Escape($StationNumber)) -TimeoutSeconds 30 -Description ("stationnummer {0}" -f $StationNumber))) {
            throw ("Stationnummer {0} werd na het invoeren niet op het Lovion-scherm gevonden." -f $StationNumber)
        }
        Assert-LovionAutomationNotCancelled

        Invoke-LovionStationOcrClick -TargetText 'EXPLORE' -Description 'de tab EXPLORE' -TimeoutSeconds 30 -MinXRatio 0.00 -MaxXRatio 0.18 -MinYRatio 0.00 -MaxYRatio 0.10 -AfterClickMilliseconds 500
        $preQuerySnapshot = Get-LovionScreenCounters -FullWindow
        $preQueryRawText = if ($null -ne $preQuerySnapshot) { [string]$preQuerySnapshot.rawText } else { '' }
        Invoke-LovionStationOcrClick -TargetText 'Start query' -Description 'Start query' -TimeoutSeconds 45 -MinXRatio 0.00 -MaxXRatio 0.22 -MinYRatio 0.04 -MaxYRatio 0.20 -FallbackRecordedX 78 -FallbackRecordedY 105 -FallbackAfterSeconds 5 -AfterClickMilliseconds 900

        $initialQueryCounters = Wait-LovionInitialStationQueryResults -PreviousRawText $preQueryRawText -TimeoutSeconds 45
        if ($null -eq $initialQueryCounters) {
            throw "De eerste zoekresultaten voor station $StationNumber konden na Start query niet betrouwbaar worden gelezen."
        }
        # Aantal geladen is the authoritative transformer count. Gefilterd is only
        # a fallback for older Lovion views that do not expose the loaded counter.
        $initialResultCount = 0
        if ($null -ne $initialQueryCounters.loaded) {
            $initialResultCount = [Math]::Max(0, [int]$initialQueryCounters.loaded)
        }
        elseif ($null -ne $initialQueryCounters.filtered) {
            $initialResultCount = [Math]::Max(0, [int]$initialQueryCounters.filtered)
        }
        Write-LovionBatchLog ("Eerste zoekresultaten station {0}: Aantal geladen={1}, gefilterd={2}; trafo's te verwerken={3}." -f $StationNumber, $initialQueryCounters.loaded, $initialQueryCounters.filtered, $initialResultCount)
    }
    if ($TransformerIndex -lt 0 -or $TransformerIndex -ge $initialResultCount) {
        throw ("Station {0} heeft {1} eerste zoekresultaten, maar trafo-index {2} werd gevraagd." -f $StationNumber, $initialResultCount, $TransformerIndex)
    }
    if ($TransformerIndex -gt 13) {
        throw ("Station {0} heeft meer dan 14 eerste zoekresultaten; trafo {1} kan niet betrouwbaar in beeld worden geselecteerd." -f $StationNumber, ($TransformerIndex + 1))
    }

    $transformerMetadata = Wait-LovionTransformerMetadata -TransformerIndex $TransformerIndex
    if ($null -eq $transformerMetadata) {
        throw ("De status van trafo {0} voor station {1} kon niet uit de resultatenlijst worden gelezen." -f ($TransformerIndex + 1), $StationNumber)
    }
    Write-LovionBatchLog ("Trafo-status station {0}, trafo {1}/{2}: {3}; asset={4}." -f $StationNumber, ($TransformerIndex + 1), $initialResultCount, $transformerMetadata.Status, $transformerMetadata.AssetId)
    if ($transformerMetadata.IsPlanned) {
        return [pscustomobject]@{
            Selected = $false
            ManualRequired = $false
            Skipped = $true
            SkipReason = 'gepland'
            ViewOpened = $false
            InitialResultCount = $initialResultCount
            TransformerIndex = $TransformerIndex
            TransformerStatus = $transformerMetadata.Status
            TransformerAssetId = $transformerMetadata.AssetId
        }
    }

    if ($initialResultCount -eq 1) {
        # With exactly one loaded result Lovion can open the active/default row
        # directly. Clicking the row is both unnecessary and unreliable in the
        # Citrix layout (it can hit the left navigation tree instead).
        Write-LovionBatchLog ("Station {0}: Aantal geladen=1; trafo-rij niet aangeklikt, direct Open > VIEW." -f $StationNumber)
    }
    else {
        # With multiple transformers, select exactly one result before Open so
        # each transformer gets its own network trace. The result-table anchor
        # is found via OCR; the generic connection-grid click would land in the
        # navigation tree on the left side of this screen.
        $transformerRowPoint = Wait-LovionTransformerResultRowPoint -VisibleRowIndex $TransformerIndex -TimeoutSeconds 35
        if ($null -eq $transformerRowPoint) {
            throw ("Trafo {0} van station {1} kon niet in de eerste resultatenlijst worden geselecteerd." -f ($TransformerIndex + 1), $StationNumber)
        }
        # Invoke-LovionStationClick throws when the native click fails. It does
        # not return $true on success, so do not wrap it in a boolean test: a
        # successful click must continue directly to Open > VIEW.
        Invoke-LovionStationClick -X $transformerRowPoint.X -Y $transformerRowPoint.Y -WaitMilliseconds 450 -Description ("trafo-resultaatrij {0}" -f ($TransformerIndex + 1))
        $selectedTransformerCount = Wait-LovionSelectedCount -TargetCount 1 -TimeoutSeconds 20
        if ($selectedTransformerCount -ne 1) {
            throw ("Trafo {0} van station {1} werd niet als één geselecteerde rij herkend; teller={2}." -f ($TransformerIndex + 1), $StationNumber, $selectedTransformerCount)
        }
    }

    Invoke-LovionStationOcrClick -TargetText 'Open' -Description 'de tab Open' -TimeoutSeconds 30 -MinXRatio 0.00 -MaxXRatio 0.18 -MinYRatio 0.00 -MaxYRatio 0.10 -AfterClickMilliseconds 500
    Invoke-LovionStationViewClick -TimeoutSeconds 45

    Set-LovionBatchStatus ("Station {0}/{1}: netwerkweergave openen" -f $StationIndex, $StationCount)
    Invoke-LovionStationOcrClick -TargetText 'Netwerk' -Description 'de netwerktab' -TimeoutSeconds 45 -MinXRatio 0.08 -MaxXRatio 0.30 -MinYRatio 0.00 -MaxYRatio 0.10 -AfterClickMilliseconds 1800
    Invoke-LovionStationOcrClick -TargetText 'Schakelaar' -Description 'Schakelaar instellen' -TimeoutSeconds 30 -MinXRatio 0.14 -MaxXRatio 0.35 -MinYRatio 0.05 -MaxYRatio 0.18 -AfterClickMilliseconds 450
    Invoke-LovionStationOcrClick -TargetText 'Rekening houden met standen van schakelaars' -Description 'de juiste schakelaaroptie' -TimeoutSeconds 30 -MinXRatio 0.15 -MaxXRatio 0.35 -MinYRatio 0.10 -MaxYRatio 0.25 -AfterClickMilliseconds 900
    Invoke-LovionStationOcrClick -TargetText 'Geen objecten' -Description 'de objecten-dropdown' -TimeoutSeconds 30 -MinXRatio 0.35 -MaxXRatio 0.55 -MinYRatio 0.05 -MaxYRatio 0.18 -AfterClickMilliseconds 450
    Invoke-LovionStationOcrClick -TargetText 'Aansluitingen' -Description 'de Aansluitingen-optie' -TimeoutSeconds 30 -MinXRatio 0.35 -MaxXRatio 0.55 -MinYRatio 0.10 -MaxYRatio 0.30 -AfterClickMilliseconds 1200

    Set-LovionBatchStatus ("Station {0}/{1}: netwerk selecteren" -f $StationIndex, $StationCount)
    $mapSelection = Invoke-LovionStationMapSelection -StationNumber $StationNumber
    if ($null -ne $mapSelection -and $mapSelection.ManualRequired) {
        return $mapSelection
    }

    Invoke-LovionStationClick -X 465 -Y 89 -WaitMilliseconds 1200 -Description 'het eerste netwerkresultaat'
    if ($null -eq (Wait-LovionScreenPattern -Pattern 'Exporteren' -TimeoutSeconds 45 -Description 'de resultaatlijst')) {
        throw 'Lovion heeft na het openen van het netwerkresultaat geen resultaatlijst getoond.'
    }
    Invoke-LovionStationOcrClick -TargetText 'Exporteren' -Description 'de aansluitingenexport' -TimeoutSeconds 30 -MinXRatio 0.40 -MaxXRatio 0.55 -MinYRatio 0.05 -MaxYRatio 0.18 -AfterClickMilliseconds 1800

    $connections = Wait-LovionConnectionsTable -TimeoutSeconds 60
    if ($null -eq $connections) {
        throw ("De LS-aansluitingenlijst voor station {0} werd niet herkend. Controleer of Lovion volledig op het linker scherm staat en de lijst LS stroomtransformatorgroep bij de start open was." -f $StationNumber)
    }
    Write-LovionBatchLog ("Stationsimport: aansluitingenlijst station {0}, trafo {1}/{2} gereed; geladen={3}, gefilterd={4}." -f $StationNumber, ($TransformerIndex + 1), $initialResultCount, $connections.loaded, $connections.filtered)
    return [pscustomobject]@{
        Selected = $true
        ManualRequired = $false
        Skipped = $false
        InitialResultCount = $initialResultCount
        TransformerIndex = $TransformerIndex
        TransformerStatus = $transformerMetadata.Status
        TransformerAssetId = $transformerMetadata.AssetId
        ConnectionCount = if ($null -ne $connections.loaded) { [int]$connections.loaded } else { [int]$connections.filtered }
    }
}

function Write-LovionStationTestCheckpoint {
    param([string]$State, [string]$ErrorMessage = '')
    if ([string]::IsNullOrWhiteSpace($script:StationTestReportPath)) { return }
    $path = [System.IO.Path]::GetFullPath($script:StationTestReportPath)
    [void][System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($path))
    $report = [ordered]@{
        State = $State
        UpdatedAt = (Get-Date).ToString('o')
        RequestedStations = $script:StationTestRequested
        Records = @($script:StationTestRecords.ToArray())
        ImportedRows = $script:Table.Rows.Count
        Error = $ErrorMessage
    }
    [System.IO.File]::WriteAllText($path, ($report | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding($false)))
    if ($script:Table.Rows.Count -gt 0) {
        # Checkpoints preserve the already prepared grid verbatim; rebuilding
        # every coordinate/address for every checkpoint is slow and unnecessary.
        $savedRows = foreach ($dataRow in $script:Table.Rows) {
            $saved = [ordered]@{}
            foreach ($column in $script:Table.Columns) {
                $value = $dataRow[$column.ColumnName]
                $saved[$column.ColumnName] = if ($value -eq [DBNull]::Value) { $null } else { [string]$value }
            }
            [pscustomobject]$saved
        }
        $savedRows | Export-Csv -LiteralPath ([System.IO.Path]::ChangeExtension($path, '.csv')) -NoTypeInformation -Encoding UTF8
    }
}

function Restore-LovionStationTestReports {
    param([string[]]$Paths)
    $restoredStations = New-Object System.Collections.Generic.List[string]
    $restoredRows = New-Object System.Collections.Generic.List[object]
    $restoredRecords = New-Object System.Collections.Generic.List[object]
    foreach ($resumePath in $Paths) {
        $path = (Resolve-Path -LiteralPath $resumePath).Path
        if (-not [string]::IsNullOrWhiteSpace($script:StationTestReportPath) -and $path -eq [System.IO.Path]::GetFullPath($script:StationTestReportPath)) { throw 'Gebruik een nieuw rapportpad bij het hervatten.' }
        $report = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        $csvPath = [System.IO.Path]::ChangeExtension($path, '.csv')
        $rows = if (Test-Path -LiteralPath $csvPath) { @(Import-Csv -LiteralPath $csvPath) } else { @() }
        $records = @($report.Records)
        $complete = @{}
        foreach ($group in @($records | Group-Object Station)) {
            $count = [int]($group.Group | Measure-Object TransformerCount -Maximum).Maximum
            $indexes = @($group.Group | Select-Object -ExpandProperty Transformer -Unique)
            if ($count -gt 0 -and $group.Count -eq $count -and $indexes.Count -eq $count -and @((1..$count) | Where-Object { $_ -notin $indexes }).Count -eq 0) {
                if ($group.Name -notin $script:StationTestRequested -or $restoredStations.Contains($group.Name)) { throw ('Onverwacht of dubbel station in hervatrapport: ' + $group.Name) }
                $complete[$group.Name] = $true
                $restoredStations.Add($group.Name)
            }
        }
        $offset = 0
        foreach ($record in $records) {
            $count = [int]$record.ImportedCount
            if ($count -lt 0 -or $count -ne [int]$record.ExpectedCount) { throw 'Ongeverifieerde teller in hervatrapport.' }
            $batch = @($rows | Select-Object -Skip $offset -First $count)
            $offset += $count
            if ($batch.Count -ne $count -or @($batch | Where-Object { $_.SourceFile -ne $record.Station }).Count -gt 0) { throw 'De opgeslagen aansluitingen passen niet bij het hervatrapport.' }
            if ($record.Outcome -eq 'planned') {
                if ($record.Status -ne 'gepland' -or $count -ne 0) { throw 'Een geplande trafo bevat ongeldige aansluitingen.' }
            } elseif ($record.Outcome -eq 'imported' -and $record.Status -eq 'in bedrijf') {
                $ids = @($batch | ForEach-Object { $_.'Master Asset ID' })
                if (@($ids | Where-Object { [string]::IsNullOrWhiteSpace($_) }).Count -gt 0 -or @($ids | Select-Object -Unique).Count -ne $count) { throw 'Ontbrekende of dubbele aansluitingen in hervatrapport.' }
            } else { throw 'Ongeverifieerde trafostatus in hervatrapport.' }
            if ($complete.ContainsKey([string]$record.Station)) {
                $restoredRecords.Add($record)
                foreach ($row in $batch) { $restoredRows.Add($row) }
            }
        }
        if ($rows.Count -ne [int]$report.ImportedRows -or $offset -gt $rows.Count) { throw 'Rijtotaal in hervatrapport is ongeldig.' }
        # Failed runs may contain an unfinished tail batch. Only rows covered
        # by verified records for fully completed stations are restored.
        Write-LovionBatchLog ('Hervatten: {0} onvolledige rijen buiten de lijst gehouden.' -f ($rows.Count - $offset))
    }
    Add-RowsToTable -Rows $restoredRows.ToArray()
    foreach ($record in $restoredRecords) { $script:StationTestRecords.Add($record) }
    Write-LovionBatchLog ('Hervatten: {0} complete stations en {1} aansluitingen behouden.' -f $restoredStations.Count, $restoredRows.Count)
    return $restoredStations.ToArray()
}

function Add-LovionStationTestRecord {
    param([string]$Station, [int]$TransformerIndex, [int]$TransformerCount, [string]$Status, [string]$Outcome, [int]$ExpectedCount, [int]$ImportedCount)
    $script:StationTestRecords.Add([pscustomobject]@{
        Station = $Station
        Transformer = $TransformerIndex + 1
        TransformerCount = $TransformerCount
        Status = $Status
        Outcome = $Outcome
        ExpectedCount = $ExpectedCount
        ImportedCount = $ImportedCount
    })
    Write-LovionStationTestCheckpoint -State 'running'
}

function Close-LovionStationResultTabs {
    Invoke-LovionStationClick -X 735 -Y 14 -WaitMilliseconds 650 -Description 'de aansluitingenresultaattab'
    Invoke-LovionStationClick -X 499 -Y 21 -WaitMilliseconds 1800 -Description 'de stationweergavetab'
    if ($null -eq (Wait-LovionScreenPattern -Pattern 'LS\s+Stroomtransformatorgroep' -TimeoutSeconds 12 -Description 'de terugkeer naar de stationslijst')) {
        throw 'Na het sluiten van de resultaat-tabs werd de lijst LS Stroomtransformatorgroep niet teruggevonden.'
    }
}

function Invoke-LovionStationsImport {
    param([string[]]$StationNumbers)

    if (-not [LovionBatchInput]::StartMouseGuard()) {
        throw 'De muisbewaking voor de stationsimport kon niet worden gestart.'
    }
    try {
        return Invoke-LovionStationsImportCore -StationNumbers $StationNumbers
    }
    finally {
        [LovionBatchInput]::ReleaseModifiers()
        [LovionBatchInput]::StopMouseGuard()
    }
}

function Invoke-LovionStationsImportCore {
    param([string[]]$StationNumbers)

    $summaries = New-Object System.Collections.Generic.List[string]
    $manualStations = New-Object System.Collections.Generic.List[string]
    $plannedTransformers = New-Object System.Collections.Generic.List[string]
    $totalImported = 0
    $stationCount = Get-CollectionCount $StationNumbers
    for ($index = 0; $index -lt $stationCount; $index += 1) {
        $station = ([string]$StationNumbers[$index]).Trim()
        try {
            $sourcePrefix = ($station -replace '[\\/:*?"<>|]', '_').Trim()
            if ([string]::IsNullOrWhiteSpace($sourcePrefix)) {
                $sourcePrefix = 'Station_{0:000}' -f ($index + 1)
            }

            # The first query tells us how many transformers belong to this
            # station. Open and import every result separately, but reuse the
            # exact same SourceFile/station number for all resulting rows.
            $transformerIndex = 0
            $transformerCount = 1
            do {
                $stationOpenParameters = @{
                    StationNumber = $station
                    StationIndex = ($index + 1)
                    StationCount = $stationCount
                    TransformerIndex = $transformerIndex
                }
                if ($transformerIndex -gt 0) {
                    # Close-LovionStationResultTabs returns to the first page of
                    # this station's already loaded results. Reuse that page for
                    # transformer 2+ instead of searching the station again.
                    $stationOpenParameters['KnownTransformerCount'] = $transformerCount
                    $stationOpenParameters['ReuseCurrentStationResults'] = $true
                }
                $stationOpenResult = Open-LovionConnectionsForStation @stationOpenParameters
                if ($null -ne $stationOpenResult -and $stationOpenResult.InitialResultCount -gt 0) {
                    $transformerCount = [Math]::Max(1, [int]$stationOpenResult.InitialResultCount)
                }

                if ((Get-ObjectPropertyValue -Object $stationOpenResult -Name 'SkipReason') -eq 'gepland') {
                    $note = '{0} trafo {1}/{2}: gepland; niet geimporteerd' -f $station, ($transformerIndex + 1), $transformerCount
                    $plannedTransformers.Add($note)
                    Write-LovionBatchLog ('Geplande trafo genoteerd voor de eindmelding: ' + $note)
                    Add-LovionStationTestRecord -Station $station -TransformerIndex $transformerIndex -TransformerCount $transformerCount -Status 'gepland' -Outcome 'planned' -ExpectedCount 0 -ImportedCount 0
                    # The query page is still open: no VIEW or connection tab was
                    # created, and the next working transformer must reuse it.
                    $transformerIndex += 1
                    continue
                }

                if ($null -ne $stationOpenResult -and $stationOpenResult.ManualRequired) {
                    if (-not $manualStations.Contains($station)) {
                        $manualStations.Add($station)
                    }
                    $summaries.Add(("{0} trafo {1}/{2}: handmatig toevoegen aan de Workbench-lijst" -f $station, ($transformerIndex + 1), $transformerCount))
                    Set-LovionBatchStatus ("Station {0}/{1}, trafo {2}/{3}: handmatige controle nodig" -f ($index + 1), $stationCount, ($transformerIndex + 1), $transformerCount)
                    Write-LovionBatchLog ("Stationsimport: {0} trafo {1}/{2} overgeslagen; handmatige toevoeging aan de Workbench-lijst vereist." -f $station, ($transformerIndex + 1), $transformerCount)

                    # There is no result tab when the map has two ambiguous markers.
                    # Close only the station-view tab and verify that the start list is
                    # back before querying the next transformer.
                    Invoke-LovionStationClick -X 499 -Y 21 -WaitMilliseconds 1200 -Description 'de stationweergavetab na handmatige kaartcontrole'
                    if ($null -eq (Wait-LovionScreenPattern -Pattern 'LS\s+Stroomtransformatorgroep' -TimeoutSeconds 20 -Description 'de stationslijst na handmatige kaartcontrole')) {
                        throw 'Na de handmatige kaartcontrole kon de stationslijst niet opnieuw worden geactiveerd.'
                    }
                    $transformerIndex += 1
                    continue
                }

                Set-LovionBatchStatus ("Station {0}/{1}, trafo {2}/{3}: aansluitingen importeren" -f ($index + 1), $stationCount, ($transformerIndex + 1), $transformerCount)
                $result = Invoke-LovionBatchImport -SourcePrefix $sourcePrefix -SkipCountdown -UseExactSourceName -SourceType 'LovionStationBatch'
                $totalImported += $result.ImportedCount
                $expectedCount = Get-ObjectPropertyValue -Object $stationOpenResult -Name 'ConnectionCount'
                $status = [string](Get-ObjectPropertyValue -Object $stationOpenResult -Name 'TransformerStatus')
                Add-LovionStationTestRecord -Station $station -TransformerIndex $transformerIndex -TransformerCount $transformerCount -Status $status -Outcome 'imported' -ExpectedCount ([int]$expectedCount) -ImportedCount $result.ImportedCount
                if ($transformerCount -gt 1) {
                    $summaries.Add(("{0} trafo {1}/{2}: {3} aansluitingen" -f $station, ($transformerIndex + 1), $transformerCount, $result.ImportedCount))
                    Write-LovionBatchLog ("Stationsimport: {0} trafo {1}/{2} afgerond met {3} aansluitingen." -f $station, ($transformerIndex + 1), $transformerCount, $result.ImportedCount)
                }
                else {
                    $summaries.Add(("{0}: {1} aansluitingen" -f $station, $result.ImportedCount))
                    Write-LovionBatchLog ("Stationsimport: {0} afgerond met {1} aansluitingen." -f $station, $result.ImportedCount)
                }
                Close-LovionStationResultTabs
                $transformerIndex += 1
            } while ($transformerIndex -lt $transformerCount)
        }
        catch {
            throw ("Station {0}: {1}" -f $station, $_.Exception.Message)
        }
    }

    return [pscustomobject]@{
        ImportedCount = $totalImported
        StationCount = $stationCount
        Summaries = $summaries.ToArray()
        ManualStations = $manualStations.ToArray()
        PlannedTransformers = $plannedTransformers.ToArray()
    }
}

function Start-LovionStationsImport {
    param([string[]]$StationNumbers, [switch]$TestRun)
    if (-not $PSBoundParameters.ContainsKey('StationNumbers')) { $stationNumbers = @(Show-StationNumbersDialog) }
    if ($stationNumbers.Count -eq 0) {
        return
    }

    $question = "Open in Lovion eerst de lijst LS stroomtransformatorgroep en selecteer alleen de eerste rij.`n`nDe Workbench verwerkt daarna {0} station(s). Bij meerdere trafo-resultaten op één station wordt iedere trafo apart geopend en geïmporteerd, maar blijft SourceFile exact hetzelfde stationnummer.`n`nLovion moet volledig zichtbaar op het linker scherm staan. De cursor blijft op de laatst gebruikte positie staan; zodra je de muis zelf beweegt, stopt de automatisering. Typ tijdens de verwerking ook niet.`n`nStarten?" -f $stationNumbers.Count
    $answer = if ($TestRun) { [System.Windows.Forms.DialogResult]::Yes } else { [System.Windows.Forms.MessageBox]::Show($script:MainForm, $question, 'Stations importeren', [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Question) }
    if ($answer -ne [System.Windows.Forms.DialogResult]::Yes) {
        return
    }

    $script:MainForm.WindowState = [System.Windows.Forms.FormWindowState]::Minimized
    [System.Windows.Forms.Application]::DoEvents()
    for ($secondsLeft = 5; $secondsLeft -gt 0; $secondsLeft -= 1) {
        Set-LovionBatchStatus ("Stationsimport start over {0} seconden..." -f $secondsLeft)
        Start-Sleep -Seconds 1
    }

    try {
        if ($TestRun) {
            # A previous test can stop while its connection result is still
            # open. Recover only that confirmed table before rerunning the
            # normal station entry point; do not assume arbitrary tabs exist.
            if (-not (Set-LovionWindowActive)) { throw 'Lovion kon voor de testrun niet worden geactiveerd.' }
            $startSnapshot = Get-LovionScreenCounters -UseLovionWindow -FullWindow
            if ((Get-LovionConnectionsTableEvidence -Snapshot $startSnapshot).Ready) {
                Write-LovionBatchLog 'Testrun: geopende aansluitingenlijst teruggezet naar de stationsquery.'
                Close-LovionStationResultTabs
            }
        }
        $result = Invoke-LovionStationsImport -StationNumbers $stationNumbers
    }
    catch {
        Write-LovionStationTestCheckpoint -State 'failed' -ErrorMessage $_.Exception.Message
        Write-LovionBatchLog ("FOUT stationsimport: {0}" -f $_.Exception.ToString())
        $script:MainForm.WindowState = [System.Windows.Forms.FormWindowState]::Normal
        $script:MainForm.Activate()
        Update-StatusBar
        if (-not $TestRun) { Show-ErrorMessage ("Stationsimport is afgebroken.`n`n{0}" -f $_.Exception.Message) }
        return
    }

    $script:MainForm.WindowState = [System.Windows.Forms.FormWindowState]::Normal
    $script:MainForm.Activate()
    Update-StatusBar
    if ($TestRun) {
        # Include restored stations and their planned notes in the final summary.
        $result.StationCount = $script:StationTestRequested.Count
        $result.ImportedCount = $script:Table.Rows.Count
        $result.Summaries = @($script:StationTestRecords | Where-Object { $_.Outcome -eq 'imported' } | ForEach-Object { '{0} trafo {1}/{2}: {3} aansluitingen' -f $_.Station, $_.Transformer, $_.TransformerCount, $_.ImportedCount })
        $result.PlannedTransformers = @($script:StationTestRecords | Where-Object { $_.Outcome -eq 'planned' } | ForEach-Object { '{0} trafo {1}/{2}: gepland; niet geimporteerd' -f $_.Station, $_.Transformer, $_.TransformerCount })
    }
    $details = if ((Get-CollectionCount $result.Summaries) -gt 0) { $result.Summaries -join "`n" } else { 'Geen aansluitingen geimporteerd.' }
    $manualText = ''
    if ((Get-CollectionCount $result.ManualStations) -gt 0) {
        $manualText = "`n`nLet op: de volgende stations hadden twee gele kaartresultaten zonder centrale marker. Voeg deze handmatig toe aan de Lovion Coordinate Workbench-lijst:`n{0}" -f ($result.ManualStations -join ', ')
    }
    $plannedText = if ($result.PlannedTransformers.Count -gt 0) { "`n`nGeplande trafo's (niet geimporteerd):`n" + ($result.PlannedTransformers -join "`n") } else { '' }
    $completionMessage = "Stationsimport klaar.`n`nStations: {0}`nAansluitingen: {1}`n`n{2}{3}{4}" -f $result.StationCount, $result.ImportedCount, $details, $manualText, $plannedText
    Write-LovionStationTestCheckpoint -State 'complete'
    Write-LovionBatchLog ($completionMessage -replace '[\r\n]+', ' | ')
    if (-not $TestRun) { Show-InfoMessage $completionMessage }
}

function Build-MainForm {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = '{0} v{1}' -f $script:AppName, $script:AppVersion
    $form.StartPosition = 'CenterScreen'
    $form.Size = New-Object System.Drawing.Size(1500, 860)
    $form.MinimumSize = New-Object System.Drawing.Size(1100, 700)
    $form.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#f5f1e8')
    $form.Font = New-Object System.Drawing.Font('Segoe UI', 9.5)
    $form.TopMost = $true
    $form.Add_Shown({
        $form.Activate()
        $form.BringToFront()
        $script:FrontTimer = New-Object System.Windows.Forms.Timer
        $script:FrontTimer.Interval = 1200
        $script:FrontTimer.Add_Tick({
            $script:FrontTimer.Stop()
            $form.TopMost = $false
        })
        $script:FrontTimer.Start()
    })

    $headerPanel = New-Object System.Windows.Forms.Panel
    $headerPanel.Dock = 'Top'
    $headerPanel.Height = 80
    $headerPanel.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#12343b')

    $titleLabel = New-Object System.Windows.Forms.Label
    $titleLabel.Text = 'Lovion Coordinate Workbench'
    $titleLabel.ForeColor = [System.Drawing.Color]::White
    $titleLabel.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 18)
    $titleLabel.Location = New-Object System.Drawing.Point(20, 14)
    $titleLabel.AutoSize = $true

    $subtitleLabel = New-Object System.Windows.Forms.Label
    $subtitleLabel.Text = 'Laad bestanden, importeer Lovion-gegevens en exporteer resultaten.'
    $subtitleLabel.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#d6e2e9')
    $subtitleLabel.Font = New-Object System.Drawing.Font('Segoe UI', 9.5)
    $subtitleLabel.Location = New-Object System.Drawing.Point(22, 48)
    $subtitleLabel.AutoSize = $true

    $headerPanel.Controls.AddRange(@($titleLabel, $subtitleLabel))

    $toolbarPanel = New-Object System.Windows.Forms.FlowLayoutPanel
    $toolbarPanel.Dock = 'Top'
    $toolbarPanel.Padding = New-Object System.Windows.Forms.Padding(14, 10, 10, 8)
    $toolbarPanel.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#e9e3d7')
    $toolbarPanel.WrapContents = $true
    $toolbarPanel.AutoScroll = $false
    $toolbarPanel.FlowDirection = 'LeftToRight'
    $toolbarPanel.AutoSize = $true
    $toolbarPanel.AutoSizeMode = 'GrowAndShrink'

    function New-ToolbarButton {
        param(
            [string]$Text,
            [string]$BackColor = '#31525b',
            [string]$ForeColor = '#ffffff',
            [int]$Width = 140
        )

        $button = New-Object System.Windows.Forms.Button
        $button.Text = $Text
        $button.Width = $Width
        $button.Height = 34
        $button.BackColor = [System.Drawing.ColorTranslator]::FromHtml($BackColor)
        $button.ForeColor = [System.Drawing.ColorTranslator]::FromHtml($ForeColor)
        $button.FlatStyle = 'Flat'
        $button.FlatAppearance.BorderSize = 0
        $button.Margin = New-Object System.Windows.Forms.Padding(0, 0, 8, 0)
        return $button
    }

    $loadButton = New-ToolbarButton -Text 'Bestanden' -BackColor '#184e77' -Width 95
    $clipboardImportButton = New-ToolbarButton -Text 'Klembord' -BackColor '#1d7874' -Width 100
    $pasteButton = New-ToolbarButton -Text 'Plakken' -BackColor '#2a9d8f' -Width 90
    $lovionBatchButton = New-ToolbarButton -Text 'Lovion 100' -BackColor '#bc6c25' -Width 105
    $stationsButton = New-ToolbarButton -Text 'Stations' -BackColor '#9b5d24' -Width 95
    $lovionMacroButton = New-ToolbarButton -Text 'Lovion macro' -BackColor '#6a4c93' -Width 115
    $removeButton = New-ToolbarButton -Text 'Verwijder' -BackColor '#9c6644' -Width 95
    $clearButton = New-ToolbarButton -Text 'Wis' -BackColor '#7f5539' -Width 70
    $csvButton = New-ToolbarButton -Text 'CSV' -BackColor '#386641' -Width 70
    $geoJsonButton = New-ToolbarButton -Text 'GeoJSON' -BackColor '#588157' -Width 90
    $shapeButton = New-ToolbarButton -Text 'Shapefile' -BackColor '#344e41' -Width 100

    $toolbarPanel.Controls.AddRange(@(
        $loadButton,
        $clipboardImportButton,
        $pasteButton,
        $lovionBatchButton,
        $stationsButton,
        $lovionMacroButton,
        $removeButton,
        $clearButton,
        $csvButton,
        $geoJsonButton,
        $shapeButton
    ))

    $grid = New-Object LovionDataGridView
    $grid.Dock = 'Fill'
    $grid.DataSource = $script:Table
    $grid.BackgroundColor = [System.Drawing.Color]::White
    $grid.BorderStyle = 'None'
    $grid.AutoSizeColumnsMode = 'DisplayedCells'
    $grid.AllowUserToOrderColumns = $true
    $grid.AllowUserToAddRows = $true
    $grid.AllowUserToDeleteRows = $true
    $grid.SelectionMode = 'FullRowSelect'
    $grid.MultiSelect = $true
    $grid.RowHeadersVisible = $false
    $grid.EnableHeadersVisualStyles = $false
    $grid.ColumnHeadersDefaultCellStyle.BackColor = [System.Drawing.ColorTranslator]::FromHtml('#dde5e8')
    $grid.ColumnHeadersDefaultCellStyle.ForeColor = [System.Drawing.ColorTranslator]::FromHtml('#102a43')
    $grid.ColumnHeadersDefaultCellStyle.Font = New-Object System.Drawing.Font('Segoe UI Semibold', 9)
    $grid.DefaultCellStyle.SelectionBackColor = [System.Drawing.ColorTranslator]::FromHtml('#d9ed92')
    $grid.DefaultCellStyle.SelectionForeColor = [System.Drawing.ColorTranslator]::FromHtml('#1b4332')

    $statusStrip = New-Object System.Windows.Forms.StatusStrip
    $statusStrip.SizingGrip = $false
    $statusLabel = New-Object System.Windows.Forms.ToolStripStatusLabel
    $statusLabel.Text = 'Rijen: 0 | Met coordinaten: 0'
    [void]$statusStrip.Items.Add($statusLabel)

    $loadButton.Add_Click({
        $dialog = New-Object System.Windows.Forms.OpenFileDialog
        $dialog.InitialDirectory = $script:CurrentDirectory
        $dialog.Multiselect = $true
        $dialog.Filter = 'Ondersteunde bestanden|*.txt;*.xlsx;*.csv|Tekstbestanden|*.txt|Excel|*.xlsx|CSV|*.csv|Alle bestanden|*.*'
        if ($dialog.ShowDialog($script:MainForm) -eq [System.Windows.Forms.DialogResult]::OK) {
            Import-FilesIntoGrid -Paths $dialog.FileNames
        }
    })

    $clipboardImportButton.Add_Click({ Import-ClipboardText })
    $pasteButton.Add_Click({ Show-PasteDialog })
    $lovionBatchButton.Add_Click({ Start-LovionBatchImport })
    $stationsButton.Add_Click({ Start-LovionStationsImport })
    $lovionMacroButton.Add_Click({ Show-LovionMacroDialog })
    $removeButton.Add_Click({ Remove-SelectedRows })
    $clearButton.Add_Click({ Clear-AllRows })

    $csvButton.Add_Click({
        try {
            $dialog = New-Object System.Windows.Forms.SaveFileDialog
            $dialog.InitialDirectory = $script:CurrentDirectory
            $dialog.Filter = 'CSV (*.csv)|*.csv'
            $dialog.FileName = 'lovion_gui_export.csv'
            if ($dialog.ShowDialog($script:MainForm) -eq [System.Windows.Forms.DialogResult]::OK) {
                Export-GridToCsv -Path $dialog.FileName
                Show-InfoMessage "CSV opgeslagen:`n$($dialog.FileName)"
            }
        }
        catch {
            Show-ErrorMessage $_.Exception.Message
        }
    })

    $geoJsonButton.Add_Click({
        try {
            $dialog = New-Object System.Windows.Forms.SaveFileDialog
            $dialog.InitialDirectory = $script:CurrentDirectory
            $dialog.Filter = 'GeoJSON (*.geojson)|*.geojson'
            $dialog.FileName = 'lovion_gui_export.geojson'
            if ($dialog.ShowDialog($script:MainForm) -eq [System.Windows.Forms.DialogResult]::OK) {
                $rows = Convert-DataTableRowsToObjects -Table $script:Table
                Export-GeoJson -Rows $rows -Path $dialog.FileName
                Show-InfoMessage "GeoJSON opgeslagen:`n$($dialog.FileName)"
            }
        }
        catch {
            Show-ErrorMessage $_.Exception.Message
        }
    })

    $shapeButton.Add_Click({
        try {
            $dialog = New-Object System.Windows.Forms.SaveFileDialog
            $dialog.InitialDirectory = $script:CurrentDirectory
            $dialog.Filter = 'Shapefile (*.shp)|*.shp'
            $dialog.FileName = 'lovion_gui_export.shp'
            if ($dialog.ShowDialog($script:MainForm) -eq [System.Windows.Forms.DialogResult]::OK) {
                $rows = Convert-DataTableRowsToObjects -Table $script:Table
                $fieldMapPath = Export-PointShapefileDynamic -Rows $rows -TargetShpPath $dialog.FileName
                Show-InfoMessage ("Shapefile opgeslagen:`n{0}`n`nFieldmap:`n{1}" -f $dialog.FileName, $fieldMapPath)
            }
        }
        catch {
            Show-ErrorMessage $_.Exception.Message
        }
    })

    $grid.Add_DataError({
        param($sender, $eventArgs)
        $eventArgs.ThrowException = $false
    })

    $grid.Add_RowsRemoved({ Update-StatusBar })
    $grid.Add_UserAddedRow({ Update-StatusBar })
    $grid.Add_CellEndEdit({ Update-StatusBar })

    $form.Controls.Add($grid)
    $form.Controls.Add($statusStrip)
    $form.Controls.Add($toolbarPanel)
    $form.Controls.Add($headerPanel)

    $script:Grid = $grid
    $script:StatusLabel = $statusLabel
    $script:MainForm = $form

    Add-TableColumn -Name 'SourceFile'
    Add-TableColumn -Name 'SourceType'
    Add-TableColumn -Name 'SourcePath'
    Add-TableColumn -Name 'RecordTitle'
    Add-TableColumn -Name 'Overdrachtspunt'
    Add-TableColumn -Name 'UsageCategory'
    Add-TableColumn -Name 'AddressQuery'
    Add-TableColumn -Name 'PdokDisplayName'
    Add-TableColumn -Name 'PdokType'
    Add-TableColumn -Name 'PdokScore'
    Add-TableColumn -Name 'PdokRdX'
    Add-TableColumn -Name 'PdokRdY'
    Add-TableColumn -Name 'PdokLon'
    Add-TableColumn -Name 'PdokLat'
    Add-TableColumn -Name 'PdokStrictMatch'
    Add-TableColumn -Name 'PdokMatchReason'
    Add-TableColumn -Name 'WfsLayer'
    Add-TableColumn -Name 'WfsDescription'
    Add-TableColumn -Name 'WfsFeatureId'
    Add-TableColumn -Name 'WfsMatchMode'
    Add-TableColumn -Name 'WfsDistanceM'
    Add-TableColumn -Name 'FinalRdX'
    Add-TableColumn -Name 'FinalRdY'
    Add-TableColumn -Name 'FinalLon'
    Add-TableColumn -Name 'FinalLat'
    Add-TableColumn -Name 'CoordinateSource'
    Add-TableColumn -Name 'MatchStatus'
    Ensure-PreferredColumnOrder
    if ($grid.Columns.Contains('SourcePath')) {
        $grid.Columns['SourcePath'].Visible = $false
    }
    Apply-GridColumnHeaders
    Update-StatusBar

    return $form
}

if ($MyInvocation.InvocationName -eq '.') {
    return
}

if ($MacroSmokeTest) {
    try {
        [xml]$macroSmokeTestXml = Get-LovionMacroXml
        if ($macroSmokeTestXml.DocumentElement.Name -ne 'Reports') {
            throw 'De ingebouwde Lovion-macro heeft geen geldige Reports-root.'
        }
        if ($macroSmokeTestXml.Reports.Report.Localizations.Localization.externalName -ne 'Trafo zoeker Macro') {
            throw 'De ingebouwde Lovion-macronaam klopt niet.'
        }
        Write-Output 'Embedded Lovion macro: PASS'
        exit 0
    }
    catch {
        Write-Error $_.Exception.Message
        exit 1
    }
}

[LovionBatchInput]::EnableDpiAwareness()
[LovionBatchInput]::HideConsoleWindow()
[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)

$form = Build-MainForm
if (-not [string]::IsNullOrWhiteSpace($OpenStationResultPath)) {
    if (-not [string]::IsNullOrWhiteSpace($StationListPath) -or -not [string]::IsNullOrWhiteSpace($StationTestReportPath)) { throw 'Open een stationsresultaat apart van een nieuwe testrun.' }
    $savedReport = Get-Content -LiteralPath $OpenStationResultPath -Raw | ConvertFrom-Json
    if ($savedReport.State -ne 'complete' -or -not [string]::IsNullOrWhiteSpace($savedReport.Error)) { throw 'Alleen een compleet stationsresultaat kan rechtstreeks worden geopend.' }
    $script:StationTestRequested = @($savedReport.RequestedStations | ForEach-Object { [string]$_ })
    $openedStations = @(Restore-LovionStationTestReports -Paths @($OpenStationResultPath))
    if ($openedStations.Count -ne $script:StationTestRequested.Count -or $script:Table.Rows.Count -ne [int]$savedReport.ImportedRows) { throw 'Het opgeslagen stationsresultaat is niet volledig.' }
}
if (-not [string]::IsNullOrWhiteSpace($StationListPath)) {
    $script:StationTestRequested = @(ConvertTo-StationNumberList -Text ([System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $StationListPath).Path)))
    if ($script:StationTestRequested.Count -eq 0 -or [string]::IsNullOrWhiteSpace($StationTestReportPath)) {
        throw 'Een stationsbestand voor een testrun vereist stationnummers en StationTestReportPath.'
    }
    $restored = @()
    if (-not [string]::IsNullOrWhiteSpace($StationTestResumePaths)) {
        $restored = @(Restore-LovionStationTestReports -Paths ($StationTestResumePaths -split ';'))
    }
    $script:StationTestPending = @($script:StationTestRequested | Where-Object { $_ -notin $restored })
    Write-LovionStationTestCheckpoint -State 'starting'
    $script:StationTestTimer = New-Object System.Windows.Forms.Timer
    $script:StationTestTimer.Interval = 1500
    $script:StationTestTimer.Add_Tick({
        $script:StationTestTimer.Stop()
        if ($script:StationTestPending.Count -gt 0) {
            Start-LovionStationsImport -StationNumbers $script:StationTestPending -TestRun
        } else {
            Write-LovionStationTestCheckpoint -State 'complete'
            Write-LovionBatchLog 'Alle gevraagde stations waren al compleet; geen dubbele import gestart.'
        }
    })
    $script:StationTestTimer.Start()
}
if ($SmokeTest) {
    $script:SmokeTestTimer = New-Object System.Windows.Forms.Timer
    $script:SmokeTestTimer.Interval = 400
    $script:SmokeTestTimer.Add_Tick({
        $script:SmokeTestTimer.Stop()
        $form.Close()
    })
    $script:SmokeTestTimer.Start()
}
[void][System.Windows.Forms.Application]::Run($form)

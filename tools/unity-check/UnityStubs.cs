// Minimal stand-ins so the pure-C# parsing logic in StateParser/MiniJson can be
// compiled and executed without the Unity editor. This file is only used by
// tools/unity-check and is never imported by the Unity project.
//
// Note: [Serializable] resolves to System.SerializableAttribute in Unity too, so
// it must NOT be stubbed here — doing so creates an ambiguous reference.
namespace UnityEngine
{
    using System;

    public sealed class TooltipAttribute : Attribute
    {
        public TooltipAttribute(string text)
        {
        }
    }
}

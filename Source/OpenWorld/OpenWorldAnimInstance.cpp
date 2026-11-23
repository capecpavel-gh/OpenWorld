// Copyright Epic Games, Inc. All Rights Reserved.

#include "OpenWorldAnimInstance.h"
#include "Animation/AnimNodeBase.h"
#include "Animation/AnimSequence.h"
#include "Animation/AnimationPoseData.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PawnMovementComponent.h"

namespace
{
	void SampleSequence(FPoseContext& Context, const UAnimSequence* Sequence, float Time)
	{
		FAnimationPoseData PoseData(Context);
		Sequence->GetAnimationPose(PoseData, FAnimExtractContext(static_cast<double>(Time), false));
	}

	/**
	 *  Blend of two bone transforms. Unlike FTransform::BlendWith it accepts rotations that are not
	 *  normalized (poses coming out of an anim graph often are not) and always returns a normalized one.
	 */
	FTransform BlendBone(const FTransform& From, const FTransform& To, float Alpha)
	{
		FQuat A = From.GetRotation().GetNormalized();
		FQuat B = To.GetRotation().GetNormalized();
		// take the short way around
		if ((A | B) < 0.0)
		{
			B = B * -1.0;
		}
		const FQuat Rotation = (A * (1.0 - Alpha) + B * Alpha).GetNormalized();
		return FTransform(Rotation,
			FMath::Lerp(From.GetTranslation(), To.GetTranslation(), static_cast<double>(Alpha)),
			FMath::Lerp(From.GetScale3D(), To.GetScale3D(), static_cast<double>(Alpha)));
	}
}

void FOpenWorldAnimInstanceProxy::PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds)
{
	Super::PreUpdate(InAnimInstance, DeltaSeconds);

	if (const UOpenWorldAnimInstance* Instance = Cast<UOpenWorldAnimInstance>(InAnimInstance))
	{
		Sequence = Instance->OverlaySequence;
		PreviousSequence = Instance->PreviousOverlaySequence;
		Time = Instance->OverlayTime;
		PreviousTime = Instance->PreviousOverlayTime;
		CrossfadeAlpha = Instance->CrossfadeAlpha;
		Weight = Instance->OverlayWeight;
		LowerBodyWeight = Instance->LowerBodyWeight;
		UpperBodyRootBone = Instance->UpperBodyRootBone;
		Stance = Instance->StanceSequence;
		PreviousStance = Instance->PreviousStanceSequence;
		StanceAlpha = Instance->StanceAlpha;
		StanceArmWeight = Instance->StanceArmWeight;
		PreviousStanceArmWeight = Instance->PreviousStanceArmWeight;
		bStanceWholeBody = Instance->bStanceWholeBody;
		bPreviousStanceWholeBody = Instance->bPreviousStanceWholeBody;
		StanceRootBones = Instance->StanceRootBones;
	}
}

bool FOpenWorldAnimInstanceProxy::Evaluate_WithRoot(FPoseContext& Output, FAnimNode_Base* InRootNode)
{
	// The Anim Blueprint graph first (locomotion, jumping...)
	EvaluateAnimationNode_WithRoot(Output, InRootNode);

	// Only the main graph gets the overlay, not linked layers
	if (InRootNode == GetRootNode())
	{
		UpdateBoneMasks(Output.Pose.GetBoneContainer());
		ApplyStance(Output);
		ApplyOverlay(Output);
	}

	return true;
}

void FOpenWorldAnimInstanceProxy::ApplyStance(FPoseContext& Output)
{
	// The pose goes from what the previous stance made of it to what the current stance makes of it.
	// A stance acts on the arms by its arm weight, and on the rest of the body only while standing.
	const bool bBlending = StanceAlpha < 1.f;
	const bool bHasTo = Stance != nullptr && (StanceArmWeight > 0.f || bStanceWholeBody);
	const bool bHasFrom = bBlending && PreviousStance != nullptr && (PreviousStanceArmWeight > 0.f || bPreviousStanceWholeBody);
	if (!bHasTo && !bHasFrom)
	{
		return;
	}

	FPoseContext To(Output);
	if (bHasTo)
	{
		SampleSequence(To, Stance, 0.f);
	}
	FPoseContext From(Output);
	if (bHasFrom)
	{
		SampleSequence(From, PreviousStance, 0.f);
	}

	for (const FCompactPoseBoneIndex BoneIndex : Output.Pose.ForEachBoneIndex())
	{
		const bool bArm = StanceMask[BoneIndex.GetInt()] != 0;
		const float ToWeight = !bHasTo ? 0.f : (bArm ? StanceArmWeight : (bStanceWholeBody ? LowerBodyWeight : 0.f));
		const float FromWeight = !bHasFrom ? 0.f : (bArm ? PreviousStanceArmWeight : (bPreviousStanceWholeBody ? LowerBodyWeight : 0.f));
		if (ToWeight <= KINDA_SMALL_NUMBER && FromWeight <= KINDA_SMALL_NUMBER)
		{
			continue;
		}

		const FTransform Source = Output.Pose[BoneIndex];
		FTransform Result = ToWeight > KINDA_SMALL_NUMBER ? BlendBone(Source, To.Pose[BoneIndex], ToWeight) : Source;
		if (bBlending)
		{
			const FTransform Start = FromWeight > KINDA_SMALL_NUMBER ? BlendBone(Source, From.Pose[BoneIndex], FromWeight) : Source;
			Result = BlendBone(Start, Result, StanceAlpha);
		}
		Output.Pose[BoneIndex] = Result;
	}
}

void FOpenWorldAnimInstanceProxy::ApplyOverlay(FPoseContext& Output)
{
	if (Sequence == nullptr || Weight <= KINDA_SMALL_NUMBER)
	{
		return;
	}

	FPoseContext Overlay(Output);
	SampleSequence(Overlay, Sequence, Time);

	const bool bCrossfading = PreviousSequence != nullptr && CrossfadeAlpha < 1.f;
	FPoseContext Previous(Output);
	if (bCrossfading)
	{
		SampleSequence(Previous, PreviousSequence, PreviousTime);
	}

	for (const FCompactPoseBoneIndex BoneIndex : Output.Pose.ForEachBoneIndex())
	{
		const float BoneWeight = Weight * (UpperBodyMask[BoneIndex.GetInt()] ? 1.f : LowerBodyWeight);
		if (BoneWeight <= KINDA_SMALL_NUMBER)
		{
			continue;
		}

		FTransform Target = Overlay.Pose[BoneIndex];
		if (bCrossfading)
		{
			Target = BlendBone(Previous.Pose[BoneIndex], Overlay.Pose[BoneIndex], CrossfadeAlpha);
		}

		FTransform& Bone = Output.Pose[BoneIndex];
		Bone = BlendBone(Bone, Target, BoneWeight);
	}
}

void FOpenWorldAnimInstanceProxy::UpdateBoneMasks(const FBoneContainer& Bones)
{
	const int32 NumBones = Bones.GetCompactPoseNumBones();
	if (UpperBodyMask.Num() == NumBones && MaskSerialNumber == Bones.GetSerialNumber()
		&& MaskRootBone == UpperBodyRootBone && MaskStanceRootBones == StanceRootBones)
	{
		return;
	}

	const FReferenceSkeleton& RefSkeleton = Bones.GetReferenceSkeleton();
	const int32 UpperBodyRoot = RefSkeleton.FindBoneIndex(UpperBodyRootBone);
	TArray<int32, TInlineAllocator<4>> StanceRoots;
	for (const FName& Name : StanceRootBones)
	{
		StanceRoots.Add(RefSkeleton.FindBoneIndex(Name));
	}

	UpperBodyMask.SetNumZeroed(NumBones);
	StanceMask.SetNumZeroed(NumBones);
	for (int32 Index = 0; Index < NumBones; ++Index)
	{
		bool bUpperBody = false;
		bool bStance = false;
		// Walk up the hierarchy: a bone belongs to a group if the group's root is the bone or one of its ancestors
		int32 MeshBone = Bones.MakeMeshPoseIndex(FCompactPoseBoneIndex(Index)).GetInt();
		while (MeshBone != INDEX_NONE)
		{
			bUpperBody |= MeshBone == UpperBodyRoot;
			bStance |= StanceRoots.Contains(MeshBone);
			MeshBone = RefSkeleton.GetParentIndex(MeshBone);
		}
		UpperBodyMask[Index] = bUpperBody ? 1 : 0;
		StanceMask[Index] = bStance ? 1 : 0;
	}

	MaskSerialNumber = Bones.GetSerialNumber();
	MaskRootBone = UpperBodyRootBone;
	MaskStanceRootBones = StanceRootBones;
}

FAnimInstanceProxy* UOpenWorldAnimInstance::CreateAnimInstanceProxy()
{
	return new FOpenWorldAnimInstanceProxy(this);
}

void UOpenWorldAnimInstance::SetStance(UAnimSequence* Sequence, float BlendTime, float ArmWeight, bool bWholeBodyWhenStanding)
{
	ArmWeight = FMath::Clamp(ArmWeight, 0.f, 1.f);
	if (Sequence == StanceSequence && FMath::IsNearlyEqual(ArmWeight, StanceArmWeight) && bWholeBodyWhenStanding == bStanceWholeBody)
	{
		return;
	}

	PreviousStanceSequence = StanceSequence;
	PreviousStanceArmWeight = StanceArmWeight;
	bPreviousStanceWholeBody = bStanceWholeBody;
	StanceSequence = Sequence;
	StanceArmWeight = ArmWeight;
	bStanceWholeBody = bWholeBodyWhenStanding;
	StanceBlendTime = FMath::Max(BlendTime, 0.f);
	StanceAlpha = StanceBlendTime > 0.f ? 0.f : 1.f;
}

void UOpenWorldAnimInstance::PlayOverlay(UAnimSequence* Sequence, float BlendInTime, float BlendOutTime)
{
	if (Sequence == nullptr)
	{
		return;
	}

	if (OverlaySequence != nullptr && OverlayWeight > 0.f)
	{
		// Cross-fade from the pose the current overlay is in right now
		PreviousOverlaySequence = OverlaySequence;
		PreviousOverlayTime = OverlayTime;
		CrossfadeAlpha = 0.f;
	}
	else
	{
		PreviousOverlaySequence = nullptr;
		CrossfadeAlpha = 1.f;
	}

	OverlaySequence = Sequence;
	OverlayTime = 0.f;
	OverlayStartWeight = OverlayWeight;
	OverlayBlendIn = FMath::Max(BlendInTime, 0.f);
	OverlayBlendOut = FMath::Max(BlendOutTime, 0.f);
	OverlayStopTime = -1.f;
	OverlayHoldRemaining = 0.f;
	OverlayFadeElapsed = 0.f;
	OverlayRewindRate = 0.f;
	bOverlayRewinding = false;
}

void UOpenWorldAnimInstance::StopOverlay(float BlendOutTime)
{
	HoldOverlay(OverlayTime, 0.f, BlendOutTime);
}

void UOpenWorldAnimInstance::HoldOverlay(float AtTime, float HoldSeconds, float BlendOutTime)
{
	if (OverlaySequence == nullptr || OverlayStopTime >= 0.f)
	{
		return;
	}

	// Never rewinds: the pose that is already on screen stays, the animation just does not go past AtTime
	OverlayStopTime = FMath::Clamp(AtTime, OverlayTime, OverlaySequence->GetPlayLength());
	OverlayHoldRemaining = FMath::Max(HoldSeconds, 0.f);
	OverlayFadeDuration = FMath::Max(BlendOutTime, KINDA_SMALL_NUMBER);
	OverlayFadeElapsed = 0.f;
	OverlayRewindRate = 0.f;
	bOverlayRewinding = false;
}

void UOpenWorldAnimInstance::HoldAndRewindOverlay(float AtTime, float HoldSeconds, float RewindRate)
{
	if (OverlaySequence == nullptr || OverlayStopTime >= 0.f)
	{
		return;
	}

	HoldOverlay(AtTime, HoldSeconds, 0.f);
	OverlayRewindRate = FMath::Max(RewindRate, 0.1f);
}

void UOpenWorldAnimInstance::NativeUpdateAnimation(float DeltaSeconds)
{
	Super::NativeUpdateAnimation(DeltaSeconds);

	// Legs follow the overlay only while standing on the ground
	bool bStanding = true;
	if (const APawn* Pawn = TryGetPawnOwner())
	{
		const UPawnMovementComponent* Movement = Pawn->GetMovementComponent();
		bStanding = Pawn->GetVelocity().Size2D() <= FullBodyMaxSpeed && !(Movement && Movement->IsFalling());
	}
	LowerBodyWeight = FMath::FInterpTo(LowerBodyWeight, bStanding ? 1.f : 0.f, DeltaSeconds, LowerBodyBlendSpeed);

	if (StanceAlpha < 1.f)
	{
		StanceAlpha = StanceBlendTime > 0.f ? FMath::Min(1.f, StanceAlpha + DeltaSeconds / StanceBlendTime) : 1.f;
		if (StanceAlpha >= 1.f)
		{
			PreviousStanceSequence = nullptr;
		}
	}

	if (OverlaySequence == nullptr)
	{
		OverlayWeight = 0.f;
		return;
	}

	// Advance, unless the overlay has reached the time it was told to stop at: then hold, then fade
	float Fade = 1.f;
	bool bRewound = false;
	if (bOverlayRewinding)
	{
		// Back along the path the pose came by; the blend-in ramp fades it out as it nears the start
		OverlayTime -= DeltaSeconds * OverlayRewindRate;
		bRewound = OverlayTime <= 0.f;
	}
	else if (OverlayStopTime >= 0.f && OverlayTime + DeltaSeconds >= OverlayStopTime)
	{
		OverlayTime = OverlayStopTime;
		if (OverlayHoldRemaining > 0.f)
		{
			OverlayHoldRemaining -= DeltaSeconds;
		}
		else if (OverlayRewindRate > 0.f)
		{
			bOverlayRewinding = true;
		}
		else
		{
			OverlayFadeElapsed += DeltaSeconds;
			Fade = 1.f - FMath::SmoothStep(0.f, 1.f, OverlayFadeElapsed / OverlayFadeDuration);
		}
	}
	else
	{
		OverlayTime += DeltaSeconds;
	}

	const float Length = OverlaySequence->GetPlayLength();
	if (OverlayTime >= Length || Fade <= 0.f || bRewound)
	{
		bOverlayRewinding = false;
		OverlaySequence = nullptr;
		PreviousOverlaySequence = nullptr;
		OverlayWeight = 0.f;
		CrossfadeAlpha = 1.f;
		OverlayStopTime = -1.f;
		return;
	}

	const float In = OverlayBlendIn > 0.f ? FMath::Clamp(OverlayTime / OverlayBlendIn, 0.f, 1.f) : 1.f;
	const float Out = OverlayBlendOut > 0.f ? FMath::Clamp((Length - OverlayTime) / OverlayBlendOut, 0.f, 1.f) : 1.f;
	OverlayWeight = Fade * FMath::Min(FMath::Lerp(OverlayStartWeight, 1.f, FMath::SmoothStep(0.f, 1.f, In)), FMath::SmoothStep(0.f, 1.f, Out));

	if (PreviousOverlaySequence != nullptr)
	{
		CrossfadeAlpha = OverlayBlendIn > 0.f ? FMath::Clamp(OverlayTime / OverlayBlendIn, 0.f, 1.f) : 1.f;
		if (CrossfadeAlpha >= 1.f)
		{
			PreviousOverlaySequence = nullptr;
		}
	}
}
